"""Prove that a write produced a physical effect, not just an echoed value.

Everything else in this repo can be satisfied by a device that stores what it
was told and advertises it back. This cannot: it writes the light object, and
then reads the *illuminance* object — a separate measurement, taken through a
different LED — out of the same advertising packet.

    python -m tools.closed_loop --address C8:80:32:AD:F7:B9

Needs a board running espruino/examples/light-loop.js. Exit status is 0 only if
the measured illuminance actually moved with the commanded state.

**On flaky hosts.** This has to hear the device, and some adapters scan badly —
the Windows machine this was developed on regularly caught four advertisements
in thirty seconds from a device advertising every two, and went deaf entirely
for stretches after each connection. "nothing heard" from this tool usually
means the host, not the board: check with a plain scan before believing it.
"""

from __future__ import annotations

import argparse
import asyncio
import sys

from bleak import BleakClient, BleakScanner

from tools.bthome_write import WRITE_CHARACTERISTIC, Watcher

# The objects light-loop.js advertises, in packet order.
PACKET_ID = 0x00
BATTERY = 0x01
ILLUMINANCE = 0x05
LIGHT = 0x1E
DECLARATION = 0xFF

WIDTHS = {PACKET_ID: 1, BATTERY: 1, ILLUMINANCE: 3, LIGHT: 1, DECLARATION: 1}

# Seconds to let the device rebuild its packet, which is when it re-reads the
# sensor. The example refreshes every 2 s.
SETTLE = 3.0


def decode(service_data: bytes) -> dict[int, int]:
    """Walk the objects and return {object id: integer value}.

    Deliberately not a general BTHome parser — it knows only this example's
    objects, which is enough here and keeps the check readable.
    """
    values: dict[int, int] = {}
    offset = 1  # skip the device-information byte
    while offset < len(service_data):
        object_id = service_data[offset]
        width = WIDTHS.get(object_id)
        if width is None or offset + 1 + width > len(service_data):
            break
        values[object_id] = int.from_bytes(
            service_data[offset + 1 : offset + 1 + width], "little"
        )
        offset += 1 + width
    return values


async def write(address: str, payload: bytes) -> None:
    async with BleakClient(address, timeout=30.0) as client:
        await client.write_gatt_char(WRITE_CHARACTERISTIC, payload, response=True)


async def fresh_packet(watcher: Watcher, after: float, timeout: float) -> bytes | None:
    """Wait for an advertisement newer than `after`.

    One scanner runs for the whole sequence rather than being restarted around
    each write: a host with a single adapter takes seconds to resume scanning
    after a disconnect, and a scanner started inside that window can miss the
    device entirely.
    """
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout
    while loop.time() < deadline:
        if watcher.at > after:
            return watcher.latest
        await asyncio.sleep(0.1)
    return None


async def run(address: str) -> int:
    print(f"{address}: closing the loop through the light sensor")
    print()

    watcher = Watcher(address)
    scanner = BleakScanner(detection_callback=watcher)
    await scanner.start()
    results: dict[bool, list[float]] = {}

    try:
        if await fresh_packet(watcher, 0.0, 60.0) is None:
            print(f"{address}: nothing heard", file=sys.stderr)
            return 1

        for on in (False, True, False):
            await write(address, bytes([LIGHT, 1 if on else 0]))
            mark = asyncio.get_running_loop().time()
            await asyncio.sleep(SETTLE)

            packet = await fresh_packet(watcher, mark + SETTLE, 25.0)
            if packet is None:
                print(f"{address}: no advertisement after the write", file=sys.stderr)
                return 1

            values = decode(packet)
            state = values.get(LIGHT)
            lux = values.get(ILLUMINANCE, 0) / 100
            label = "on " if on else "off"
            print(f"  commanded {label}   {packet.hex()}")
            print(f"                 light={state}  illuminance={lux:.1f}")

            if state != (1 if on else 0):
                print(f"FAIL: commanded {label}, device advertises {state}")
                return 1
            results.setdefault(on, []).append(lux)
    finally:
        await scanner.stop()

    dark = sum(results[False]) / len(results[False])
    lit = sum(results[True]) / len(results[True])
    print()
    print(f"  mean illuminance, LED off: {dark:.1f}")
    print(f"  mean illuminance, LED on:  {lit:.1f}")

    if lit <= dark:
        print(
            "FAIL: the measurement did not move. Either the LED is not lighting, "
            "or it is not in the sensor's view.",
            file=sys.stderr,
        )
        return 1

    print()
    print(
        f"the commanded LED is measurably lighting the sensor: "
        f"+{lit - dark:.1f}, {lit / max(dark, 0.01):.1f}x"
    )
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--address", required=True)
    args = parser.parse_args()
    return asyncio.run(run(args.address))


if __name__ == "__main__":
    sys.exit(main())
