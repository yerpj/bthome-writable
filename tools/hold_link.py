"""Hold a link open and do nothing, which is an arm of its own.

Every other measurement in this project connects in order to write something.
The case nobody has measured is a central that connects and then sits there --
the Web IDE while you read the console, Espruino Hub, a dashboard holding a
link it does not need. That is the only case where a pinned connection interval
(D-141) is paid for continuously rather than per command, so it is arm H of
§23 and it needs a central that connects and stays quiet.

    python -m tools.hold_link --address E0:A4:BA:16:54:89 --seconds 120
    python -m tools.hold_link --address E0:A4:BA:16:54:89 --seconds 120 \\
        --statement 'NRF.setConnectionInterval(7.5);'

With `--statement` the line is sent over the Nordic UART console first and the
link is then left alone for the rest of the window, which is how the same run
measures the pinned arm without reloading the sketch.

A connection is a write on a shared bench (`docs/shared-bench.md`): take the
lock first.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
import time

from bleak import BleakClient, BleakScanner

UART_RX = "6e400002-b5a3-f393-e0a9-e50e24dcca9e"


async def run(address: str, seconds: float, statement: str | None) -> int:
    device = await BleakScanner.find_device_by_address(address, timeout=40.0)
    if device is None:
        print(f"{address}: not seen", file=sys.stderr)
        return 1

    async with BleakClient(
        device, timeout=30.0, winrt={"use_cached_services": False}
    ) as client:
        started = time.monotonic()
        print(f"connected to {address}")
        if statement:
            data = (statement.rstrip("\n") + "\n").encode()
            for offset in range(0, len(data), 50):
                await client.write_gatt_char(
                    UART_RX, data[offset : offset + 50], response=True
                )
            print(f"sent: {statement}")
        print(f"holding the link for {seconds:.0f} s, sending nothing")
        await asyncio.sleep(seconds)
        print(f"disconnecting after {time.monotonic() - started:.1f} s")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--address", required=True)
    parser.add_argument("--seconds", type=float, default=120.0)
    parser.add_argument(
        "--statement", help="one console line to send before going quiet"
    )
    args = parser.parse_args(argv)

    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    return asyncio.run(run(args.address, args.seconds, args.statement))


if __name__ == "__main__":
    sys.exit(main())
