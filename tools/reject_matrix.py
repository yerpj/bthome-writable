"""Check that a device rejects malformed writes, and says why.

PROTOCOL.md §4.2 makes a write a closed format: wrong object ID, short, or with
trailing bytes, and the device must reject the *whole* thing rather than apply
the part it understood. That strictness is a safety property — a permissive
parser is what would let a replayed advertisement apply its objects — so it is
worth testing against a real device rather than only in unit tests.

One BLE connection carries both the entry's characteristic and Espruino's console,
so this writes each bad payload and reads back what the board printed, which is
the rejection code the module raised.

    python -m tools.reject_matrix --address C8:80:32:AD:F7:B9

The example sketch must be running with its `onError` hook, which prints
"write rejected: <code> <message>" -- light-loop.js does, and exposes
`lamp.on`, which is checked to be unchanged afterwards.
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import sys

from tools.espruino_deploy import connect, discover
from tools.ha_protocol import characteristic_uuid
from tools.multi_instance import Console

# payload, what it exercises, the code the module should raise
CASES: list[tuple[str, str, str | None]] = [
    ("1f01", "an object ID that is not the entry's", "objectid_mismatch"),
    ("1e", "a value cut short", "truncated"),
    ("", "an empty write", "truncated"),
    (
        "1e01ff02",
        "trailing bytes -- a second object smuggled into one write",
        "trailing_bytes",
    ),
]


async def run(address: str, entry: int, state: str) -> int:
    device = await discover(address, 120.0)
    if device is None:
        print(f"{address}: not seen", file=sys.stderr)
        return 1
    client = await connect(device)
    failures = 0
    try:
        console = Console(client)
        await console.start()
        before = await console.ask(state)
        print(f"{state} before: {before}\n")

        for payload_hex, description, expected in CASES:
            console.buffer.clear()
            await client.write_gatt_char(
                characteristic_uuid(entry), bytes.fromhex(payload_hex), response=True
            )
            await asyncio.sleep(1.0)
            got = None
            for line in console.printed().splitlines():
                if "write rejected:" in line:
                    got = line.split("write rejected:")[1].strip().split()[0]
            ok = got == expected
            failures += 0 if ok else 1
            shown = payload_hex or "(empty)"
            print(f"{'ok  ' if ok else 'FAIL'} {shown:<10} {description}")
            print(f"       expected {expected}, got {got}")

        # A rejected write applies nothing at all.
        after = await console.ask(state)
        print(f"\n{state} after:  {after}")
        if before is None or after != before:
            print("FAIL: a rejected write changed the state", file=sys.stderr)
            failures += 1
        else:
            print("ok   the state is unchanged")
    finally:
        with contextlib.suppress(Exception):
            await client.disconnect()
    return 1 if failures else 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--address", required=True)
    parser.add_argument("--entry", type=int, default=1, help="a light entry")
    parser.add_argument(
        "--state", default="lamp.on", help="a sketch expression holding the state"
    )
    args = parser.parse_args()
    return asyncio.run(run(args.address, args.entry, args.state))


if __name__ == "__main__":
    sys.exit(main())
