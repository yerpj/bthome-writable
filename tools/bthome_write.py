"""Write one entry of a bthome-writable device, and time it.

This is the protocol's whole round trip in one command: read the declaration
from the advertising, connect, write one object to the entry's characteristic
with response, optionally read it back, disconnect (PROTOCOL.md §4).

    python -m tools.bthome_write --address C8:80:32:AD:F7:B9 --payload 1e01
    python -m tools.bthome_write --address ... --entry 2 --payload 1e00 --read

Exit status is 0 only if the device acknowledged the write. Version 2 has no
confirming advertisement: the write response is the acknowledgement that the
bytes arrived, and whether the device *applied* them is the device's business
(§3) -- `tools.closed_loop` is the check that it did.

**On the latency it reports.** On Windows the adapter stops delivering
advertisements around a connection and takes seconds to resume, so a first
advertisement can be slow to arrive; that says nothing about the device (D-047).
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import sys
import time

from bleak import BleakClient, BleakScanner

from tools.ha_protocol import ProtocolError, characteristic_uuid, parse_declaration

BTHOME_UUID_PREFIX = "0000fcd2"


class Watcher:
    """Keeps the latest BTHome service data seen from one address."""

    def __init__(self, address: str) -> None:
        self.address = address.upper()
        self.latest: bytes | None = None
        self.at: float = 0.0
        self.history: list[tuple[float, bytes]] = []

    def __call__(self, device, advertisement) -> None:
        if device.address.upper() != self.address:
            return
        for uuid, data in advertisement.service_data.items():
            if uuid.startswith(BTHOME_UUID_PREFIX):
                self.latest = bytes(data)
                self.at = time.monotonic()
                self.history.append((self.at, bytes(data)))


def declared_object_id(service_data: bytes, entry: int) -> int | None:
    """The object ID the device declares for `entry`, if it declares one."""
    with contextlib.suppress(ProtocolError):
        declaration = parse_declaration(service_data[1:])  # minus device info
        if declaration is not None and 0 < entry <= len(declaration.entries):
            return declaration.entries[entry - 1].object_id
    return None


async def first_advertisement(watcher: Watcher, seconds: float) -> bytes | None:
    deadline = time.monotonic() + seconds
    while watcher.latest is None and time.monotonic() < deadline:
        await asyncio.sleep(0.2)
    return watcher.latest


async def run(address: str, entry: int, payload: bytes, read: bool) -> int:
    watcher = Watcher(address)
    scanner = BleakScanner(detection_callback=watcher)
    await scanner.start()
    try:
        print("waiting for a first advertisement ...")
        heard = await first_advertisement(watcher, 15)
    finally:
        with contextlib.suppress(Exception):
            await scanner.stop()
    if heard is None:
        print(f"{address}: nothing heard -- is it advertising?", file=sys.stderr)
        return 1

    print(f"advertising {heard.hex()}")
    object_id = declared_object_id(heard, entry)
    if object_id is None:
        print(f"entry {entry} is not declared", file=sys.stderr)
        return 1
    if payload and payload[0] != object_id:
        print(
            f"note: entry {entry} is object 0x{object_id:02x}; the device "
            "must refuse this write (§4.2)"
        )

    uuid = characteristic_uuid(entry)
    print(f"writing  {payload.hex()} to entry {entry} ({uuid})")
    started = time.monotonic()
    async with BleakClient(address, timeout=30.0) as client:
        connected = time.monotonic()
        await client.write_gatt_char(uuid, payload, response=True)
        written = time.monotonic()
        if read:
            characteristic = client.services.get_characteristic(uuid)
            if characteristic is None or "read" not in characteristic.properties:
                print("         not readable: the device reports no state (§3.1)")
            else:
                value = bytes(await client.read_gatt_char(uuid))
                print(f"read     {value.hex()}")
    print(
        f"         connect {(connected - started) * 1000:.0f} ms, "
        f"write {(written - connected) * 1000:.0f} ms, "
        f"total {(time.monotonic() - started) * 1000:.0f} ms"
    )
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--address", required=True, help="the device's BLE address")
    parser.add_argument(
        "--entry", type=int, default=1, help="the declared entry to write (from 1)"
    )
    parser.add_argument(
        "--payload",
        required=True,
        help="object ID then value, in hex, e.g. 1e01 (PROTOCOL.md §4.2)",
    )
    parser.add_argument(
        "--read", action="store_true", help="read the characteristic back"
    )
    args = parser.parse_args()

    payload = bytes.fromhex(args.payload.replace(" ", ""))
    return asyncio.run(run(args.address, args.entry, payload, args.read))


if __name__ == "__main__":
    sys.exit(main())
