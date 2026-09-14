"""Put a Home Assistant sensor value on a BLE screen.

    python -m tools.push_text --address CD:F5:77:3A:B2:16 \
        --entity sensor.bureau_mobilesensf7b9_illuminance
    python -m tools.push_text --address CD:F5:77:3A:B2:16 --text "hello"

This is the shape the project started from: a value that lives in Home
Assistant, shown on a device that polls nothing and was configured by nobody.
The write is an ordinary BTHome-writable write (PROTOCOL.md §4.2) carrying one
text object.

A text object is write-only, so **there is no confirmation** (§3): the device
never advertises what it was told, and a lost write is silent. What this does
instead is read the device's console back and report the line the sketch prints
when it draws -- which is a debugging aid, not a protocol feature. A real
receiver has nothing equivalent.
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import json
import os
import re
import sys
import urllib.request

from tools.espruino_deploy import UART_RX, UART_TX, connect, discover

WRITE_CHARACTERISTIC = "2faa0002-3b0b-4b1a-9e2a-b4c2952e62f2"
TEXT_OBJECT_ID = 0x53
NOISE = re.compile(r"\x1b\[[0-9;]*[A-Za-z]|[\r\x00-\x08\x0b-\x1f]")


def from_home_assistant(entity: str) -> str:
    """The entity's state and unit, as short as it can be put."""
    token = os.environ.get("HA_TOKEN")
    if not token:
        raise SystemExit("HA_TOKEN is not set")
    base = os.environ.get("HA_URL", "http://haosjry.local:8123")
    request = urllib.request.Request(
        f"{base}/api/states/{entity}", headers={"Authorization": f"Bearer {token}"}
    )
    with urllib.request.urlopen(request, timeout=20) as response:
        state = json.load(response)
    unit = state.get("attributes", {}).get("unit_of_measurement", "")
    name = state.get("attributes", {}).get("friendly_name", entity)
    # The panel is 128 px wide: the reading matters, the entity id does not.
    short = name.split()[-1]
    return f"{short} {state['state']}{unit}"


def compose(text: str) -> bytes:
    """One text object, length-prefixed, as §4.2 frames a write."""
    body = text.encode("ascii", errors="replace")
    if len(body) > 255:
        raise SystemExit(f"{len(body)} bytes is beyond a BTHome length byte")
    return bytes([TEXT_OBJECT_ID, len(body)]) + body


async def run(address: str, text: str) -> int:
    payload = compose(text)
    device = await discover(address, 120.0)
    if device is None:
        print(f"{address}: not seen", file=sys.stderr)
        return 1

    client = await connect(device)
    console = bytearray()
    try:
        with contextlib.suppress(Exception):
            await client.start_notify(UART_TX, lambda _s, data: console.extend(data))
        print(f"writing {len(payload)} bytes: {payload.hex()}")
        await client.write_gatt_char(WRITE_CHARACTERISTIC, payload, response=True)
        await asyncio.sleep(1.0)
        # Ask rather than listen. Catching the sketch's own console.log is a
        # race -- the line can be printed before the notification subscription
        # is live -- while reading the variable back is not.
        console.clear()
        question = b'print("SHOWN=", JSON.stringify(shown));\n'
        for offset in range(0, len(question), 50):
            await client.write_gatt_char(
                UART_RX, question[offset : offset + 50], response=False
            )
            await asyncio.sleep(0.03)
        await asyncio.sleep(1.2)
    finally:
        with contextlib.suppress(Exception):
            await client.disconnect()

    said = NOISE.sub("", console.decode("utf-8", "replace"))
    for line in said.splitlines():
        stripped = line.strip()
        if "rejected" in stripped:
            print(f"device: {stripped[:160]}")
            return 1
        if stripped.startswith("SHOWN=") and "print(" not in stripped:
            got = stripped[6:].strip()
            print(f"device is showing: {got}")
            return 0 if got.strip('"') == text else 1
    print("the device did not answer; for a write-only object that proves nothing")
    return 1


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--address", required=True)
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--text", help="literal text to display")
    source.add_argument("--entity", help="a Home Assistant entity to read")
    args = parser.parse_args()

    text = args.text if args.text else from_home_assistant(args.entity)
    print(f"text: {text!r}")
    return asyncio.run(run(args.address, text))


if __name__ == "__main__":
    sys.exit(main())
