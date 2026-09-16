"""Run the shared AES-CCM test vectors on a real board.

`ha/tests/test_encryption.py` proves the receiver agrees with the vectors, and
`espruino/test` proves the module's arithmetic agrees with them in Node. Neither
proves anything about the firmware in front of you: Espruino's `crypto` module
is a build-time option, its AES has at least one mode that ignores the argument
it is given (D-027), and `AES.encrypt` fails on large inputs long before memory
runs out (D-028). All three of those were found on hardware, by running the
vectors on hardware.

    python -m tools.verify_device_ccm --address CD:F5:77:3A:B2:16

It uploads `AESCCM.js` to Storage, feeds it each vector, and compares what the
board computes with what the contract says. It changes nothing else: no
application is installed, `.bootcde` is not touched, and the board is left
disconnected -- an Espruino accepts one central at a time, and a held link locks
Home Assistant out until someone power-cycles it (D-043).
"""

from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path
import re
import sys
import zlib

from tools.espruino_deploy import (
    WRITE_ATTEMPTS,
    connect,
    discover,
    prepare,
    write_statements,
)
from tools.espruino_upload import UART_RX, UART_TX

ROOT = Path(__file__).resolve().parents[1]
MODULE = ROOT / "espruino" / "AESCCM.js"
VECTORS = ROOT / "test-vectors" / "test-vectors.json"

# From spec/PROTOCOL.md §5.1. The direction lives in the nonce, which is why a
# recorded advertisement cannot be replayed as a write.
DEVICE_INFO = {"advertising": 0x41, "write": 0xFF}

NOISE = re.compile(r"\x1b\[[0-9;]*[A-Za-z]|[\x00-\x08\x0b\x0c\x0e-\x1f]")

# Defined once on the device rather than inlined into every vector, so that a
# statement stays short enough for a console with no flow control (D-031).
HELPERS = (
    "function hx(a){return [].map.call(a,function(b){"
    'return (b+256).toString(16).slice(-2)}).join("")}\n'
    'function hexOf(o){return hx(o.data)+":"+hx(o.mic)}\n'
)


def js_bytes(hex_string: str) -> str:
    """A hex string as a JavaScript byte array literal."""
    values = ",".join(str(b) for b in bytes.fromhex(hex_string))
    return f"new Uint8Array([{values}])"


def nonce(mac: str, direction: str, counter: int) -> bytes:
    """13 bytes: mac || D2 FC || device-info || counter, little-endian."""
    return (
        bytes.fromhex(mac.replace(":", ""))
        + b"\xd2\xfc"
        + bytes([DEVICE_INFO[direction]])
        + counter.to_bytes(4, "little")
    )


def cases() -> list[dict]:
    """Every vector whose MIC is meant to verify, both directions.

    The negative vectors are deliberately left out: they test that a *receiver*
    refuses something, which is not a question about this firmware's arithmetic.
    """
    vectors = json.loads(VECTORS.read_text(encoding="utf-8"))["vectors"]
    return [v for v in vectors if v.get("mic_valid")]


def expected(vector: dict) -> tuple[str, str]:
    """The ciphertext and MIC this vector says the board must produce."""
    payload = bytes.fromhex(vector["payload"])
    if vector["direction"] == "advertising":
        payload = payload[1:]  # strip the device-information byte
    ciphertext, mic = payload[:-8], payload[-4:]
    return ciphertext.hex(), mic.hex()


async def main(address: str, scan_timeout: float) -> int:
    source = prepare(MODULE.read_text(encoding="utf-8"))
    vectors = cases()
    print(f"{MODULE.name}  ({len(source)} bytes)   {len(vectors)} vectors")

    device = await discover(address, scan_timeout)
    if device is None:
        print(f"{address}: not seen in {scan_timeout:.0f}s", file=sys.stderr)
        return 1

    console = bytearray()
    client = await connect(device)
    try:
        await asyncio.wait_for(
            client.start_notify(UART_TX, lambda _s, data: console.extend(data)),
            timeout=20,
        )

        async def send(text: str, settle: float = 0.3) -> None:
            data = text.encode("utf-8")
            for offset in range(0, len(data), 50):
                await asyncio.wait_for(
                    client.write_gatt_char(
                        UART_RX, data[offset : offset + 50], response=False
                    ),
                    timeout=20,
                )
                await asyncio.sleep(0.02)
            await asyncio.sleep(settle)

        async def ask(statement: str, settle: float = 1.0) -> str:
            console.clear()
            await send(statement + "\n", settle)
            text = NOISE.sub("", console.decode("utf-8", "replace"))
            for line in text.splitlines():
                if line.strip().startswith("R="):
                    return line.split("=", 1)[1].strip()
            return ""

        await send("\x03")
        await send("clearInterval();clearWatch();\n")

        have = await ask('print("R="+(typeof require("crypto").AES))')
        if have != "function":
            print(
                f"{address}: this firmware has no AES ({have or 'no answer'}). "
                "Rebuild it with the crypto module; there is no JavaScript "
                "fallback (D-026).",
                file=sys.stderr,
            )
            return 2
        print("firmware has AES")

        for _attempt in range(WRITE_ATTEMPTS):
            print("uploading AESCCM ...")
            for statement in write_statements("AESCCM", source):
                await send(statement + "\n", settle=0.25)
            crc = await ask(
                'print("R="+(E.CRC32(require("Storage").read("AESCCM"))>>>0))', 1.2
            )
            want = zlib.crc32(source.encode("ascii")) & 0xFFFFFFFF
            if crc.isdigit() and int(crc) == want:
                break
            print(f"  stored crc {crc or '?'} is wrong -- rewriting")
        else:
            print("AESCCM: still damaged after every attempt", file=sys.stderr)
            return 1

        await send('Modules.removeAllCached();var ccm=require("AESCCM");\n', 0.6)

        await send(HELPERS, 0.6)

        failures = 0
        for vector in vectors:
            want_ct, want_mic = expected(vector)
            iv = nonce(vector["mac"], vector["direction"], vector["counter"])
            statement = (
                'print("R="+hexOf(ccm.encrypt('
                f"{js_bytes(vector['plaintext'])},"
                f"{js_bytes(vector['bindkey'])},"
                f"{js_bytes(iv.hex())},"
                "4)))"
            )
            got = await ask(statement, 1.0)
            ok = got == f"{want_ct}:{want_mic}"
            failures += not ok
            mark = "ok  " if ok else "FAIL"
            print(f"  {mark} {vector['name']:<34} {vector['direction']}")
            if not ok:
                print(f"       device {got or '(no answer)'}")
                print(f"       wanted {want_ct}:{want_mic}")

        print()
        if failures:
            print(f"{failures} of {len(vectors)} vectors disagree with the contract")
            return 1
        print(f"all {len(vectors)} vectors match on {address}")
        return 0
    finally:
        await client.disconnect()


def cli() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--address", required=True)
    parser.add_argument("--scan-timeout", type=float, default=25.0)
    args = parser.parse_args()
    return asyncio.run(main(args.address, args.scan_timeout))


if __name__ == "__main__":
    sys.exit(cli())
