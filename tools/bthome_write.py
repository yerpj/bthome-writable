"""Write to a bthome-writable device and time how long the confirmation takes.

This is the protocol's whole round trip in one command: connect, write,
disconnect, then watch the air until the device's advertising reflects what was
written (PROTOCOL.md §6). It exists because "did the write work" and "how long
did the confirmation take" are the two questions the hardware tests keep asking,
and because the answer to the second one is what the receiver's confirmation
window has to be larger than.

    python -m tools.bthome_write --address C8:80:32:AD:F7:B9 --payload 1e01

Exit status is 0 only if the device advertised the written value.

**On the latency it reports.** A host with one Bluetooth adapter cannot scan
while it is connected, so the measured confirmation time includes however long
the adapter takes to resume scanning after the disconnect — measured at four to
eight seconds on Windows, which says nothing about the device. Treat the number
as an upper bound and a smoke test. The figure that matters comes from the
receiver that will really be listening: a Home Assistant host that scans
continuously, or a second adapter dedicated to scanning.
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import sys
import time

from bleak import BleakClient, BleakScanner

BTHOME_UUID_PREFIX = "0000fcd2"
WRITE_CHARACTERISTIC = "639333f3-f21f-4558-9d85-06fcac3436c2"


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


def contains(payload: bytes, expected: bytes) -> bool:
    """Whether the advertised objects carry the value that was written.

    The write is `<objectID><value>` pairs and the advertisement carries those
    same pairs somewhere in its object stream, so a substring test is enough
    and does not need the packet's layout.
    """
    return expected in payload


async def run(address: str, payload: bytes, timeout: float) -> int:
    watcher = Watcher(address)
    scanner = BleakScanner(detection_callback=watcher)
    await scanner.start()
    try:
        print("waiting for a first advertisement ...")
        deadline = time.monotonic() + 15
        while watcher.latest is None and time.monotonic() < deadline:
            await asyncio.sleep(0.2)
        if watcher.latest is None:
            print(f"{address}: nothing heard — is it advertising?", file=sys.stderr)
            return 1

        before = watcher.latest
        print(f"before   {before.hex()}")

        if contains(before, payload):
            print(
                "note: the device already advertises this value; "
                "the confirmation below proves nothing on its own"
            )

        print(f"writing  {payload.hex()}")
        connected_at = time.monotonic()
        async with BleakClient(address, timeout=30.0) as client:
            await client.write_gatt_char(WRITE_CHARACTERISTIC, payload, response=True)
        wrote_at = time.monotonic()
        print(
            f"         connect + write + disconnect took "
            f"{(wrote_at - connected_at) * 1000:.0f} ms"
        )

        deadline = wrote_at + timeout
        while time.monotonic() < deadline:
            if watcher.at > wrote_at and contains(watcher.latest, payload):
                latency = (watcher.at - wrote_at) * 1000
                print(f"after    {watcher.latest.hex()}")
                print(f"confirmed in {latency:.0f} ms")
                return 0
            await asyncio.sleep(0.05)

        print(f"after    {watcher.latest.hex() if watcher.latest else '(nothing)'}")
        print(
            f"NOT confirmed within {timeout:.1f} s — the device either rejected "
            "the write or did not refresh its advertising",
            file=sys.stderr,
        )
        return 1
    finally:
        with contextlib.suppress(Exception):
            await scanner.stop()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--address", required=True, help="the device's BLE address")
    parser.add_argument(
        "--payload",
        required=True,
        help="the write payload in hex, e.g. 1e01 (PROTOCOL.md §4.2)",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=10.0,
        help="seconds to wait for the confirming advertisement",
    )
    args = parser.parse_args()

    payload = bytes.fromhex(args.payload.replace(" ", ""))
    return asyncio.run(run(args.address, payload, args.timeout))


if __name__ == "__main__":
    sys.exit(main())
