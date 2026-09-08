"""Check that a device rejects malformed writes, and says why.

PROTOCOL.md §4.2 makes a write a closed format: wrong object ID, short, or with
trailing bytes, and the device must reject the *whole* thing rather than apply
the part it understood. That strictness is a safety property — a permissive
parser is what would let a replayed advertisement apply its objects — so it is
worth testing against a real device rather than only in unit tests.

One BLE connection carries both the write characteristic and Espruino's console,
so this writes each bad payload and reads back what the board printed, which is
the rejection code the module raised.

    python -m tools.reject_matrix --address C8:80:32:AD:F7:B9

The example sketch must be running with its `onError` hook, which prints
"write rejected: <code> <message>".
"""

from __future__ import annotations

import argparse
import asyncio
import sys

from bleak import BleakClient, BleakScanner

from tools.bthome_write import WRITE_CHARACTERISTIC, Watcher

UART_TX = "6e400003-b5a3-f393-e0a9-e50e24dcca9e"

# payload, what it exercises, the code the module should raise
CASES: list[tuple[str, str, str | None]] = [
    (
        "1f01",
        "an object ID the device does not have at that position",
        "objectid_mismatch",
    ),
    ("1e", "a value cut short", "truncated"),
    ("", "an empty write", "truncated"),
    (
        "1e01ff02",
        "trailing bytes -- what a replayed advertisement looks like",
        "trailing_bytes",
    ),
]


async def run(address: str) -> int:
    watcher = Watcher(address)
    scanner = BleakScanner(detection_callback=watcher)
    await scanner.start()
    try:
        deadline = asyncio.get_running_loop().time() + 15
        while watcher.latest is None and asyncio.get_running_loop().time() < deadline:
            await asyncio.sleep(0.2)
        if watcher.latest is None:
            print(f"{address}: nothing heard", file=sys.stderr)
            return 1
        before = watcher.latest
        print(f"advertising before: {before.hex()}\n")
    finally:
        await scanner.stop()

    console = bytearray()
    failures = 0

    async with BleakClient(address, timeout=30.0) as client:
        await client.start_notify(UART_TX, lambda _s, data: console.extend(data))

        for payload_hex, description, expected in CASES:
            console.clear()
            payload = bytes.fromhex(payload_hex)
            await client.write_gatt_char(WRITE_CHARACTERISTIC, payload, response=True)
            await asyncio.sleep(1.0)

            printed = console.decode("utf-8", errors="replace")
            got = None
            for line in printed.splitlines():
                if "write rejected:" in line:
                    got = line.split("write rejected:")[1].strip().split()[0]

            ok = got == expected
            failures += 0 if ok else 1
            status = "ok  " if ok else "FAIL"
            shown = payload_hex or "(empty)"
            print(f"{status} {shown:<10} {description}")
            print(f"       expected {expected}, got {got}")

    # Whatever the device did with those writes, its advertised state must not
    # have moved: a rejected write applies nothing at all.
    watcher = Watcher(address)
    scanner = BleakScanner(detection_callback=watcher)
    await scanner.start()
    try:
        deadline = asyncio.get_running_loop().time() + 15
        while watcher.latest is None and asyncio.get_running_loop().time() < deadline:
            await asyncio.sleep(0.2)
    finally:
        await scanner.stop()

    after = watcher.latest
    print(f"\nadvertising after:  {after.hex() if after else '(nothing)'}")
    if after is None:
        print("could not re-read the advertising", file=sys.stderr)
        return 1

    # Compare the objects, not the packet id, which moves on every refresh.
    if strip_packet_id(before) != strip_packet_id(after):
        print("FAIL: a rejected write changed the advertised state", file=sys.stderr)
        failures += 1
    else:
        print("ok   the advertised state is unchanged")

    return 1 if failures else 0


def strip_packet_id(payload: bytes) -> bytes:
    """Drop the device-info byte and the packet-id object (`00 <n>`)."""
    if len(payload) >= 3 and payload[1] == 0x00:
        return payload[3:]
    return payload[1:]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--address", required=True)
    args = parser.parse_args()
    return asyncio.run(run(args.address))


if __name__ == "__main__":
    sys.exit(main())
