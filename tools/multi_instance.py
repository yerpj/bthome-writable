"""T2.2 on hardware: does position really address the instance?

    python -m tools.multi_instance --address C8:80:32:AD:F7:B9

Needs a board running espruino/examples/three-lights.js.

PROTOCOL.md §2.1 makes position the addressing primitive: three `light` objects
share one object ID, and the only thing distinguishing the second from the third
is where it sits in the packet. Everything else in this repository tests that
against fixtures, where both sides count the same way by construction. This
tests it where the counting is done twice, independently, by a host and by a
device that has sorted its own objects.

The failure it is looking for is not an error. A protocol that got this wrong
would switch the wrong light and report success, so each write is checked
against the advertising that follows: exactly one position changed, and it was
the intended one.

Then the other half of §4.2 — a write whose object IDs do not match the layout
must be rejected whole, not applied in part (risk #8).
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import sys

from bleak import BleakScanner

from tools.espruino_deploy import UART_TX, connect, discover
from tools.ha_protocol import ProtocolError, parse_declaration

BTHOME_UUID = "0000fcd2-0000-1000-8000-00805f9b34fb"
WRITE_CHARACTERISTIC = "2faa0002-3b0b-4b1a-9e2a-b4c2952e62f2"


async def latest_declaration(address: str, seconds: float = 25.0):
    """The device's current declaration, from its own advertising."""
    wanted = address.upper()
    seen: list[bytes] = []

    def heard(device, advertisement) -> None:
        payload = advertisement.service_data.get(BTHOME_UUID)
        if device.address.upper() == wanted and payload:
            seen.append(payload)

    async with BleakScanner(heard):
        await asyncio.sleep(seconds)

    if not seen:
        return None
    with contextlib.suppress(ProtocolError):
        # Minus the device-information byte, which is not part of the objects.
        return parse_declaration(seen[-1][1:])
    return None


def states(declaration) -> list[int]:
    """The advertised on/off of each writable object, in packet order."""
    return [obj.value[0] for obj in declaration.objects]


def compose(values: list[int], object_ids: list[int]) -> bytes:
    """Write-all in packet order: every writable object, id then value."""
    payload = bytearray()
    for object_id, value in zip(object_ids, values, strict=True):
        payload.append(object_id)
        payload.append(value)
    return bytes(payload)


async def run(address: str) -> int:
    declaration = await latest_declaration(address)
    if declaration is None:
        print(f"{address}: heard no declaration", file=sys.stderr)
        return 1

    object_ids = [obj.object_id for obj in declaration.objects]
    count = len(object_ids)
    print(f"declared writable: {count} objects at positions {declaration.positions}")
    if count < 2 or len(set(object_ids)) != 1:
        print("this test wants several objects of one ID", file=sys.stderr)
        return 1

    device = await discover(address, 120.0)
    client = await connect(device)
    failures = 0
    try:
        with contextlib.suppress(Exception):
            await client.start_notify(UART_TX, lambda _s, _d: None)

        for target in range(count):
            before = states(declaration)
            wanted = list(before)
            wanted[target] = 0 if before[target] else 1

            payload = compose(wanted, object_ids)
            print(f"\nposition {target}: {before} -> {wanted}  ({payload.hex()})")
            await client.write_gatt_char(WRITE_CHARACTERISTIC, payload, response=True)
            await asyncio.sleep(1.0)

            declaration = await latest_declaration(address, 12.0)
            if declaration is None:
                print("  no advertisement heard back")
                failures += 1
                continue
            after = states(declaration)
            moved = [i for i in range(count) if after[i] != before[i]]
            if moved == [target]:
                print(f"  ok   advertised {after}")
            else:
                failures += 1
                print(f"  FAIL advertised {after}; {moved} moved, wanted [{target}]")

        # Risk #8: the IDs are redundant given the position, and that redundancy
        # is what catches a receiver writing against a layout the device no
        # longer has. A wrong ID must lose the whole write, not part of it.
        before = states(declaration)
        desync = bytearray(compose(before, object_ids))
        desync[0] = 0x0F  # generic, where the device expects a light
        desync[1] = 1 if before[0] == 0 else 0
        print(f"\ndesynchronised write ({bytes(desync).hex()}) -- must be refused")
        await client.write_gatt_char(WRITE_CHARACTERISTIC, bytes(desync), response=True)
        await asyncio.sleep(1.0)

        declaration = await latest_declaration(address, 12.0)
        after = states(declaration) if declaration else None
        if after == before:
            print(f"  ok   advertised {after}, unchanged")
        else:
            failures += 1
            print(f"  FAIL advertised {after}, was {before}")
    finally:
        with contextlib.suppress(Exception):
            await client.disconnect()

    if failures:
        print(f"\n{failures} failure(s)")
    else:
        print("\nevery position addressed the object it names")
    return 1 if failures else 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--address", required=True)
    args = parser.parse_args()
    return asyncio.run(run(args.address))


if __name__ == "__main__":
    sys.exit(main())
