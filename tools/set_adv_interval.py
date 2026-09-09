"""Change a device's idle advertising interval, live.

This is the knob that trades battery against how long the first command of a
burst waits, and the only way to choose it well is to try values against a real
receiver. Reflashing to try a number is a poor way to do that, so the module
exposes `setAdvertisingInterval()` and this drives it over the console.

    python -m tools.set_adv_interval --address C8:80:32:AD:F7:B9 --ms 500
    python -m tools.set_adv_interval --address C8:80:32:AD:F7:B9 --ms 500 --save

Without `--save` the change lasts until the device reboots, which is usually
what you want while trying values out.
"""

from __future__ import annotations

import argparse
import asyncio
import re
import sys

from bleak import BleakClient, BleakScanner

UART_RX = "6e400002-b5a3-f393-e0a9-e50e24dcca9e"
UART_TX = "6e400003-b5a3-f393-e0a9-e50e24dcca9e"

# Espruino dresses console output with carriage returns and ANSI escapes.
NOISE = re.compile(r"\x1b\[[0-9;]*[A-Za-z]|[\r\x00-\x08\x0b-\x1f]")


async def run(address: str, ms: int, save: bool) -> int:
    device = await BleakScanner.find_device_by_address(address, timeout=40.0)
    if device is None:
        print(f"{address}: not seen", file=sys.stderr)
        return 1

    console = bytearray()
    async with BleakClient(
        device, timeout=30.0, winrt={"use_cached_services": False}
    ) as client:
        await client.start_notify(UART_TX, lambda _s, data: console.extend(data))

        async def send(text: str) -> None:
            data = text.encode()
            for offset in range(0, len(data), 50):
                await client.write_gatt_char(
                    UART_RX, data[offset : offset + 50], response=True
                )
            await asyncio.sleep(1.5)

        await send("\n")
        console.clear()
        await send(f'print("ADV=", bw.setAdvertisingInterval({ms}));\n')
        if save:
            print("saving to flash ...")
            await send("save();\n")
            await asyncio.sleep(4)

    printed = NOISE.sub("", console.decode("utf-8", errors="replace"))
    for line in printed.splitlines():
        if line.startswith("ADV="):
            print(f"idle advertising interval is now {line[4:].strip()} ms")
            return 0
        if "Uncaught" in line:
            print(line, file=sys.stderr)
            return 1

    print("the device did not confirm the change", file=sys.stderr)
    return 1


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--address", required=True)
    parser.add_argument("--ms", type=int, required=True, help="20 to 10000")
    parser.add_argument(
        "--save", action="store_true", help="persist it across a reboot"
    )
    args = parser.parse_args()
    return asyncio.run(run(args.address, args.ms, args.save))


if __name__ == "__main__":
    sys.exit(main())
