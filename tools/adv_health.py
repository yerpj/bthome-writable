"""Listen to the bench and say whether what it hears is well formed (D-111).

Home Assistant's log held two payloads attributed to these boards whose `0xFF`
declaration byte was gone, which makes `bthome-ble` read the rest of the packet
as objects and warn that object ids are out of order. What the boards actually
advertise parsed cleanly at the same moment, so the question was not *is the
packet right* but *how often does a wrong one arrive, and on which side of the
radio*. This answers it with a count rather than an anecdote.

    .venv-ha/Scripts/python.exe -m tools.adv_health [seconds]

Passive: it only listens, so it needs no bench lock and disturbs nothing. It
also prints how many *distinct* payloads each board sent, which is the plainest
view of D-106 and D-109 from outside the device -- a board whose readings have
not moved advertises the same packet over and over, and should.

A payload counts as well formed when it starts with a BTHome v2
device-information byte, its object ids ascend, and the last object is the
declaration.
"""

from __future__ import annotations

import asyncio
import collections
import sys

from bleak import BleakScanner

from tools.devices import DEVICES

WANT = {config["address"].upper(): name for name, config in DEVICES.items()}
UUID = "0000fcd2-0000-1000-8000-00805f9b34fb"
WINDOW = float(sys.argv[1]) if len(sys.argv) > 1 else 180.0

SIZES = {0x00: 1, 0x01: 1, 0x02: 2, 0x05: 3, 0x1E: 1, 0x53: None}
"""The objects the bench's two examples advertise, and their payload lengths.

Not a BTHome table: `tools.bthome_fixtures` and the upstream module own that.
`None` means the object carries its own length byte, as text does. An object
this does not know makes the payload unreadable here, which is reported as such
rather than guessed at."""


def well_formed(payload: bytes) -> tuple[bool, str]:
    if not payload or payload[0] & 0x1F != 0x00 or not payload[0] & 0x40:
        return False, "device-information byte"
    i, last_id, saw_declaration = 1, -1, False
    while i < len(payload):
        oid = payload[i]
        if oid < last_id:
            return False, f"0x{oid:02x} after 0x{last_id:02x}"
        last_id = oid
        if oid == 0xFF:
            if i + 1 >= len(payload):
                return False, "declaration without a length"
            length = payload[i + 1]
            i += 2 + length
            saw_declaration = True
            if i != len(payload):
                return False, "declaration is not last"
            continue
        if oid not in SIZES:
            return False, f"0x{oid:02x} is not in this tool's table"
        size = SIZES[oid]
        if size is None:
            if i + 1 >= len(payload):
                return False, f"0x{oid:02x} without a length"
            size = payload[i + 1] + 1
        i += 1 + size
        if i > len(payload):
            return False, f"0x{oid:02x} runs past the end"
    return (saw_declaration, "ok" if saw_declaration else "no declaration")


async def main():
    seen = collections.Counter()
    bad = collections.defaultdict(list)
    payloads = collections.defaultdict(collections.Counter)

    def on(device, adv):
        key = device.address.upper()
        if key not in WANT or UUID not in adv.service_data:
            return
        payload = bytes(adv.service_data[UUID])
        seen[key] += 1
        payloads[key][payload.hex()] += 1
        ok, why = well_formed(payload)
        if not ok:
            bad[key].append((payload.hex(), why))

    scanner = BleakScanner(detection_callback=on)
    await scanner.start()
    await asyncio.sleep(WINDOW)
    await scanner.stop()

    for address, name in WANT.items():
        total = seen[address]
        wrong = bad[address]
        print(f"\n{name} {address}: {total} advertisements in {WINDOW:.0f} s, "
              f"{len(payloads[address])} distinct payloads, {len(wrong)} malformed")
        for hexed, why in wrong[:8]:
            print(f"   {hexed}  ({why})")


if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
asyncio.run(main())
