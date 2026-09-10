"""Run espruino/AESCCM.js on a real board, against the shared test vectors.

    python -m tools.ccm_bench --address C8:80:32:AD:F7:B9

T1.3 asked for "ms/frame, and go/no-go on JS CCM". The answer needed no
JavaScript AES: Puck.js has no `AES.ccmEncrypt` -- the firmware guards CCM
behind `USE_AES_CCM`, unset in this build -- but CCM is a CBC-MAC plus a
counter-mode keystream, and both come from the native AES it does have.

`espruino/test/ccm.test.js` checks the same module under Node with OpenSSL
supplying the AES. This checks it on the silicon that will run it, which is the
half Node cannot speak for: the module is written to Storage and `require`d,
exactly as a device would use it.

It also re-checks the CTR defect that forced the ECB route (decisions.md D-027).
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import json
from pathlib import Path
import re
import sys

from tools.espruino_deploy import (
    UART_RX,
    UART_TX,
    connect,
    discover,
    prepare,
    write_statements,
)

ROOT = Path(__file__).resolve().parent.parent
VECTORS_FILE = ROOT / "test-vectors" / "test-vectors.json"
MODULE_FILE = ROOT / "espruino" / "AESCCM.js"

NOISE = re.compile(r"\x1b\[[0-9;]*[A-Za-z]|[\r\x00-\x08\x0b-\x1f]")

IV_A = "000102030405060708090a0b0c0d0e0f"
IV_B = "ffeeddccbbaa99887766554433221100"

# Hex helpers, kept on the host side so the module under test stays untouched.
HELPERS = [
    "function hx(h){var a=new Uint8Array(h.length/2);"
    "for(var i=0;i<a.length;i++)a[i]=parseInt(h.substr(i*2,2),16);return a;}",
    'function sx(a){if(a===null)return "null";a=new Uint8Array(a);var s="";'
    "for(var i=0;i<a.length;i++){var b=a[i].toString(16);"
    's+=b.length<2?"0"+b:b;}return s;}',
    "var Z=new Uint8Array(16);",
]


def split_payload(vector: dict, mic_length: int) -> tuple[str, str]:
    """(ciphertext, mic) from a vector's on-the-wire payload."""
    payload = bytes.fromhex(vector["payload"])
    if vector["direction"] == "advertising":
        payload = payload[1:]
    return payload[: -4 - mic_length].hex(), payload[-mic_length:].hex()


async def run(address: str) -> int:
    document = json.loads(VECTORS_FILE.read_text(encoding="utf-8"))
    mic_length = document["constants"]["mic_length"]
    cases = document["vectors"]

    device = await discover(address, 180.0)
    if device is None:
        print(f"{address}: not seen", file=sys.stderr)
        return 1

    client = await connect(device)
    out = bytearray()
    try:
        await client.start_notify(UART_TX, lambda _s, data: out.extend(data))

        async def send(text: str, settle: float = 0.3) -> None:
            data = text.encode()
            for offset in range(0, len(data), 50):
                await client.write_gatt_char(
                    UART_RX, data[offset : offset + 50], response=False
                )
                await asyncio.sleep(0.02)
            await asyncio.sleep(settle)

        await send("\x03")
        await send("clearInterval();clearWatch();\n")
        out.clear()

        # Install the module the way a device would hold it, then require it:
        # what runs here is the file in the repository, not a copy of it.
        print(f"installing AESCCM ({MODULE_FILE.stat().st_size} bytes of source) ...")
        for statement in write_statements(
            "AESCCM", prepare(MODULE_FILE.read_text("utf-8"))
        ):
            await send(statement + "\n", settle=0.25)
        for line in HELPERS:
            await send(line + "\n")
        await send('var ccm=require("AESCCM");\n', settle=1.0)
        await send('print("READY=", typeof ccm.encrypt, typeof ccm.decrypt);\n')

        # Is CTR really unusable? Two IVs with nothing in common.
        await send("var K0=new Uint8Array(16);\n")
        for name, iv in (("CTRA", IV_A), ("CTRB", IV_B)):
            await send(
                f'print("{name}=", sx(AES.encrypt(Z,K0,'
                f'{{iv:hx("{iv}"),mode:"CTR"}})));\n'
            )

        # One self-contained statement per line, computing and printing at once.
        # Assigning to a variable and printing it separately reads better and is
        # a trap: a line the board drops -- and it drops them, there being no
        # flow control on this console -- leaves the previous vector's value in
        # place, so every later vector cheerfully reprints the first one's
        # answer. This way a lost line prints nothing, which the host can see.
        for case in cases:
            key, nonce = case["bindkey"], case["nonce"]
            if case.get("mic_valid"):
                await send(
                    f'print("E={case["name"]}", (function(){{'
                    f'var r=ccm.encrypt(hx("{case["plaintext"]}"),hx("{key}"),'
                    f'hx("{nonce}"),{mic_length});'
                    f'return sx(r.data)+" "+sx(r.mic);}})());\n',
                    settle=0.6,
                )
            ciphertext, mic = split_payload(case, mic_length)
            await send(
                f'print("D={case["name"]}", sx(ccm.decrypt(hx("{ciphertext}"),'
                f'hx("{key}"),hx("{nonce}"),hx("{mic}"))));\n',
                settle=0.6,
            )

        first = next(c for c in cases if c.get("mic_valid"))
        await send(
            f'var K=hx("{first["bindkey"]}"),N=hx("{first["nonce"]}"),'
            f'P=hx("{first["plaintext"]}");\n'
        )
        # Ten, not fifty: on a Puck.js already running a sketch, a tighter loop
        # outruns the garbage collector and AES.encrypt starts returning
        # undefined ("Not enough memory for result"), which then surfaces as a
        # wrong answer rather than as the resource problem it is.
        await send('print("MEMFREE=", process.memory().free);\n')
        await send(
            'print("MS=",(function(){var t=getTime();'
            f"for(var i=0;i<10;i++)ccm.encrypt(P,K,N,{mic_length});"
            "return (getTime()-t)*1000/10;})().toFixed(2));\n",
            settle=5.0,
        )
        await send('print("MEMAFTER=", process.memory().free);\n')
    finally:
        with contextlib.suppress(Exception):
            await client.disconnect()

    encrypted: dict[str, tuple[str, str]] = {}
    decrypted: dict[str, str] = {}
    ctr: dict[str, str] = {}
    memory: dict[str, str] = {}
    timing = ready = ""
    for line in NOISE.sub("", out.decode("utf-8", "replace")).splitlines():
        text = line.strip()
        if text.startswith("E="):
            parts = text.split()
            if len(parts) >= 3:
                encrypted[parts[0][2:]] = (parts[1], parts[2])
        elif text.startswith("D="):
            parts = text.split()
            if len(parts) >= 2:
                decrypted[parts[0][2:]] = parts[1]
        elif text.startswith(("CTRA=", "CTRB=")):
            ctr[text[:4]] = text.split("=", 1)[1].strip()
        elif text.startswith(("MS=", "MEMFREE=", "MEMAFTER=")):
            key = text.split("=", 1)[0]
            value = text.split("=", 1)[1].strip()
            if key == "MS":
                timing = value
            else:
                memory[key] = value
        elif text.startswith("READY="):
            ready = text.split("=", 1)[1].strip()

    for line in NOISE.sub("", out.decode("utf-8", "replace")).splitlines():
        if "Uncaught" in line:
            print(f"device error: {line.strip()}", file=sys.stderr)

    if "function function" not in ready:
        print(
            f"the module did not load on the device (READY={ready!r})", file=sys.stderr
        )
        return 1

    failures = 0
    for case in cases:
        name = case["name"]
        if case.get("mic_valid"):
            got = encrypted.get(name)
            want = (case["ciphertext"], case["mic"])
            if got != want:
                failures += 1
                print(f"FAIL {name}: encrypt -> {got}, want {want}")
            elif decrypted.get(name) != case["plaintext"]:
                failures += 1
                print(f"FAIL {name}: decrypt -> {decrypted.get(name)}")
            else:
                print(f"ok   {name}")
        else:
            # A bad MIC must come back as null, whatever else is wrong with it.
            if decrypted.get(name) != "null":
                failures += 1
                print(f"FAIL {name}: expected rejection, got {decrypted.get(name)}")
            else:
                print(f"ok   {name} (rejected: {case.get('reject_reason')})")

    if failures:
        # The console is the only witness to what the board actually saw, and a
        # dropped character shows up here as a truncated line rather than as a
        # wrong answer.
        print("\n--- console tail ---", file=sys.stderr)
        transcript = NOISE.sub("", out.decode("utf-8", "replace")).splitlines()
        for line in transcript[-40:]:
            print(line[:160], file=sys.stderr)

    print(f"\n{len(cases) - failures}/{len(cases)} vectors reproduced on-device")
    if timing:
        print(f"encrypt: {timing} ms per frame")
    if memory:
        print(
            f"RAM free: {memory.get('MEMFREE')} -> {memory.get('MEMAFTER')} blocks "
            "(with the sketch and the module both resident)"
        )
    if ctr.get("CTRA") and ctr["CTRA"] == ctr.get("CTRB"):
        print("CTR: iv ignored -- identical output for unrelated IVs (D-027)")
    return 1 if failures else 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--address", required=True)
    args = parser.parse_args()
    return asyncio.run(run(args.address))


if __name__ == "__main__":
    sys.exit(main())
