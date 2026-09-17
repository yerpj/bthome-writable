"""T2.2 on hardware: does the entry number really address the instance?

    python -m tools.multi_instance --address C8:80:32:AD:F7:B9

Needs a board running espruino/examples/three-lights.js.

PROTOCOL.md §2.1 makes the entry number the addressing primitive: three `light`
entries share one object ID, and the only thing distinguishing the second from
the third is which characteristic they are served on. Everything else in this
repository tests that against fixtures, where both sides count the same way by
construction. This tests it where the counting is done twice, independently, by
a host and by a device that has sorted its own objects.

The failure it is looking for is not an error. A protocol that got this wrong
would switch the wrong light and report success. Light state is never
advertised (§2.3), so each write is checked by asking the sketch over its
console: exactly one lamp changed, and it was the intended one.

Then the other half of §4.2 -- a write whose object ID does not match the entry
must be refused, and change nothing.
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import json
import re
import sys

from bleak import BleakScanner

from tools.bthome_write import Watcher, first_advertisement
from tools.espruino_deploy import UART_RX, UART_TX, connect, discover
from tools.ha_protocol import characteristic_uuid, parse_declaration

NOISE = re.compile(r"\x1b\[[0-9;]*[A-Za-z]|[\r\x00-\x08\x0b-\x1f]")
LIGHT = 0x1E


class Console:
    """The sketch's REPL, asked one expression at a time."""

    def __init__(self, client) -> None:
        self.client = client
        self.buffer = bytearray()

    async def start(self) -> None:
        await self.client.start_notify(
            UART_TX, lambda _s, data: self.buffer.extend(data)
        )

    async def ask(self, expression: str, seconds: float = 1.2) -> str | None:
        """Evaluate `expression` on the device and return what it printed."""
        self.buffer.clear()
        line = f'print("ANSWER=" + JSON.stringify({expression}));\n'.encode()
        for offset in range(0, len(line), 50):
            await self.client.write_gatt_char(
                UART_RX, line[offset : offset + 50], response=False
            )
            await asyncio.sleep(0.03)
        await asyncio.sleep(seconds)
        said = NOISE.sub("", self.buffer.decode("utf-8", "replace"))
        for text in said.splitlines():
            stripped = text.strip()
            if stripped.startswith("ANSWER=") and "print(" not in stripped:
                return stripped[len("ANSWER=") :]
        return None

    def printed(self) -> str:
        return NOISE.sub("", self.buffer.decode("utf-8", "replace"))


async def lamps(console: Console) -> list[bool] | None:
    answer = await console.ask("lamps.map(function (l) { return l.on; })")
    return json.loads(answer) if answer else None


async def run(address: str) -> int:
    watcher = Watcher(address)
    async with BleakScanner(detection_callback=watcher):
        heard = await first_advertisement(watcher, 25)
    if heard is None:
        print(f"{address}: nothing heard", file=sys.stderr)
        return 1
    declaration = parse_declaration(heard[1:])
    if declaration is None:
        print(f"{address}: no declaration in {heard.hex()}", file=sys.stderr)
        return 1
    ids = [e.object_id for e in declaration.entries]
    print(f"declared writable: {[f'0x{i:02x}' for i in ids]}")
    if len(ids) < 2 or set(ids) != {LIGHT}:
        print("this test wants several light entries", file=sys.stderr)
        return 1

    device = await discover(address, 120.0)
    client = await connect(device)
    failures = 0
    try:
        console = Console(client)
        await console.start()
        before = await lamps(console)
        if before is None:
            print("the sketch did not answer; is three-lights.js running?")
            return 1

        for entry in range(1, len(ids) + 1):
            wanted = not before[entry - 1]
            payload = bytes([LIGHT, int(wanted)])
            await client.write_gatt_char(
                characteristic_uuid(entry), payload, response=True
            )
            after = await lamps(console)
            moved = [i + 1 for i in range(len(ids)) if after and after[i] != before[i]]
            if moved == [entry]:
                print(f"  ok   entry {entry} <- {payload.hex()}: lamps {after}")
            else:
                failures += 1
                print(f"  FAIL entry {entry} <- {payload.hex()}: {moved} moved")
            before = after or before

        # §4.2: the object ID is redundant given the characteristic, and that
        # redundancy is what catches a receiver writing against a layout the
        # device no longer has.
        wrong = bytes([0x0F, int(not before[0])])
        print(f"\nwrong object ID on entry 1 ({wrong.hex()}) -- must be refused")
        console.buffer.clear()
        await client.write_gatt_char(characteristic_uuid(1), wrong, response=True)
        await asyncio.sleep(1.0)
        rejected = "objectid_mismatch" in console.printed()
        after = await lamps(console)
        if after == before and rejected:
            print(f"  ok   refused (objectid_mismatch), lamps {after}")
        else:
            failures += 1
            print(f"  FAIL lamps {after}, was {before}; rejection logged: {rejected}")
    finally:
        with contextlib.suppress(Exception):
            await client.disconnect()

    print(
        f"\n{failures} failure(s)" if failures else "\nevery entry addressed its lamp"
    )
    return 1 if failures else 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--address", required=True)
    args = parser.parse_args()
    return asyncio.run(run(args.address))


if __name__ == "__main__":
    sys.exit(main())
