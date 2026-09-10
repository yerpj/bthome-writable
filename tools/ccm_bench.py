"""T1.3: is AES-CCM affordable on an nRF52, and does it produce the right bytes?

    python -m tools.ccm_bench --address C8:80:32:AD:F7:B9

The task breakdown asks for "ms/frame, and go/no-go on JS CCM". The answer turns
out not to need a JavaScript AES at all: Puck.js has no `AES.ccmEncrypt` -- the
firmware guards CCM behind `USE_AES_CCM`, which this build does not set -- but
it has native CBC and ECB, and CCM is made of exactly those. The composition
lives in `ccm_probe.js`.

This checks it against the shared test vectors rather than merely timing it,
because a fast wrong answer is worth nothing. It also re-checks the CTR defect
that forced the ECB route: see spec/for-gordon.md.
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import json
from pathlib import Path
import re
import sys

from tools.espruino_deploy import UART_RX, UART_TX, connect, discover

ROOT = Path(__file__).resolve().parent.parent
VECTORS_FILE = ROOT / "test-vectors" / "test-vectors.json"
PROBE_FILE = Path(__file__).resolve().parent / "ccm_probe.js"

NOISE = re.compile(r"\x1b\[[0-9;]*[A-Za-z]|[\r\x00-\x08\x0b-\x1f]")

IV_A = "000102030405060708090a0b0c0d0e0f"
IV_B = "ffeeddccbbaa99887766554433221100"


def probe_lines() -> list[str]:
    """The JavaScript, one console statement per line, comments dropped."""
    source = PROBE_FILE.read_text(encoding="utf-8")
    source = re.sub(r"/\*.*?\*/", "", source, flags=re.S)
    return [line.strip() for line in source.splitlines() if line.strip()]


def vectors() -> list[dict]:
    data = json.loads(VECTORS_FILE.read_text(encoding="utf-8"))["vectors"]
    return [v for v in data if v["direction"] == "advertising" and v.get("mic_valid")]


async def run(address: str) -> int:
    cases = vectors()
    device = await discover(address, 180.0)
    if device is None:
        print(f"{address}: not seen", file=sys.stderr)
        return 1

    client = await connect(device)
    out = bytearray()
    try:
        await client.start_notify(UART_TX, lambda _s, data: out.extend(data))

        async def send(text: str, settle: float = 0.35) -> None:
            data = text.encode()
            for offset in range(0, len(data), 50):
                await client.write_gatt_char(
                    UART_RX, data[offset : offset + 50], response=False
                )
                await asyncio.sleep(0.02)
            await asyncio.sleep(settle)

        await send("\x03")
        out.clear()
        for line in probe_lines():
            await send(line + "\n")

        # Is CTR really unusable? Two IVs with nothing in common.
        await send("var K0=new Uint8Array(16);\n")
        for name, iv in (("CTRA", IV_A), ("CTRB", IV_B)):
            await send(
                f'print("{name}=", sx(AES.encrypt(Z,K0,'
                f'{{iv:hx("{iv}"),mode:"CTR"}})));\n'
            )

        for case in cases:
            await send(
                f'var K=hx("{case["bindkey"]}"),N=hx("{case["nonce"]}"),'
                f'P=hx("{case["plaintext"]}");var r=ccm(P,K,N,4);\n'
            )
            await send(f'print("V={case["name"]}", sx(r.data), sx(r.mic));\n')

        first = cases[0]
        await send(
            f'var K=hx("{first["bindkey"]}"),N=hx("{first["nonce"]}"),'
            f'P=hx("{first["plaintext"]}");\n'
        )
        await send(
            'print("MS=",(function(){var t=getTime();'
            "for(var i=0;i<100;i++)ccm(P,K,N,4);"
            "return (getTime()-t)*1000/100;})().toFixed(2));\n",
            settle=4.0,
        )
        await send(
            'print("AESMS=",(function(){'
            "var b=new Uint8Array(32),A=new Uint8Array(32);var t=getTime();"
            'for(var i=0;i<100;i++){AES.encrypt(b,K,{iv:Z,mode:"CBC"});'
            'AES.encrypt(A,K,{mode:"ECB"});}'
            "return (getTime()-t)*1000/100;})().toFixed(2));\n",
            settle=3.0,
        )
    finally:
        with contextlib.suppress(Exception):
            await client.disconnect()

    got: dict[str, tuple[str, str]] = {}
    ctr: dict[str, str] = {}
    timing: dict[str, str] = {}
    for line in NOISE.sub("", out.decode("utf-8", "replace")).splitlines():
        text = line.strip()
        if text.startswith("V="):
            parts = text.split()
            if len(parts) >= 3:
                got[parts[0][2:]] = (parts[1], parts[2])
        elif text.startswith(("CTRA=", "CTRB=")):
            ctr[text[:4]] = text.split("=", 1)[1].strip()
        elif text.startswith(("MS=", "AESMS=")):
            timing[text.split("=")[0]] = text.split("=", 1)[1].strip()

    failures = 0
    for case in cases:
        if case["name"] not in got:
            print(f"?    {case['name']}: no answer from the device")
            failures += 1
            continue
        ciphertext, mic = got[case["name"]]
        if ciphertext == case["ciphertext"] and mic == case["mic"]:
            print(f"ok   {case['name']}")
        else:
            failures += 1
            print(f"FAIL {case['name']}")
            print(f"       want {case['ciphertext']} {case['mic']}")
            print(f"       got  {ciphertext} {mic}")

    print(f"\n{len(cases) - failures}/{len(cases)} vectors reproduced on-device")
    if timing:
        print(f"CCM frame:    {timing.get('MS')} ms")
        print(f"of which AES: {timing.get('AESMS')} ms")
    if ctr.get("CTRA") and ctr["CTRA"] == ctr.get("CTRB"):
        print("CTR: iv ignored -- identical output for unrelated IVs")
    return 1 if failures else 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--address", required=True)
    args = parser.parse_args()
    return asyncio.run(run(args.address))


if __name__ == "__main__":
    sys.exit(main())
