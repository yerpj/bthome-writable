"""Find out how much text a writable BTHome device will actually accept.

The protocol says a text object is `0x53 <length> <bytes>` and that a receiver
should negotiate an MTU of at least 64 (PROTOCOL.md §4.4). What a real stack
does is another matter, and the answer decides whether "show a sensor value on a
screen" is a sensible thing to build on this.

So this writes text of increasing length and reads back, over the device's own
console, what actually arrived — the only way to tell a write that was rejected
from one that silently went nowhere, since a write-only object has no
confirmation to offer (§3).

    python -m tools.text_limits --address C8:80:32:AD:F7:B9

Needs a board running espruino/examples/display-text.js.
"""

from __future__ import annotations

import argparse
import asyncio
import re
import sys

from bleak import BleakClient, BleakScanner

WRITE_CHARACTERISTIC = "2faa0002-3b0b-4b1a-9e2a-b4c2952e62f2"
UART_RX = "6e400002-b5a3-f393-e0a9-e50e24dcca9e"
UART_TX = "6e400003-b5a3-f393-e0a9-e50e24dcca9e"

TEXT_OBJECT = 0x53

# Espruino dresses its console output with carriage returns and ANSI escapes, so
# a plain startswith() on a line never matches what it printed. Cost an entire
# run of this tool reading "vanished: no reaction at all" for writes the device
# had in fact applied.
NOISE = re.compile(r"\x1b\[[0-9;]*[A-Za-z]|[\r\x00-\x08\x0b-\x1f]")

# Lengths worth probing: either side of what a default 23-byte MTU carries, and
# on up to the characteristic's declared maximum.
LENGTHS = (4, 20, 24, 46, 48, 50, 64, 80, 100, 120, 126, 128, 160)


def payload_for(length: int) -> bytes:
    """A text write of exactly `length` characters, each identifiable."""
    text = "".join(chr(ord("a") + (i % 26)) for i in range(length))
    return bytes([TEXT_OBJECT, length]) + text.encode("ascii")


async def run(address: str, response: bool) -> int:
    device = await BleakScanner.find_device_by_address(address, timeout=40.0)
    if device is None:
        print(f"{address}: not seen", file=sys.stderr)
        return 1

    console = bytearray()
    results: list[tuple[int, int, str]] = []

    # Never through a cached GATT table. An Espruino device rebuilds its table
    # on every upload, so a host's cache is stale by construction here, and a
    # write resolved through it lands on a handle that no longer means anything
    # — reported as success, with the device doing nothing (decisions.md D-012).
    async with BleakClient(
        device, timeout=30.0, winrt={"use_cached_services": False}
    ) as client:
        await client.start_notify(UART_TX, lambda _s, data: console.extend(data))
        # Nudge the console so the board starts talking to this connection.
        await client.write_gatt_char(UART_RX, b"\n", response=True)
        await asyncio.sleep(0.6)

        mtu = getattr(client, "mtu_size", None)
        print(f"connected, MTU {mtu} -> {(mtu or 23) - 3} bytes in a simple write")
        print(f"writing with response={response}")
        print()
        print(f"  {'write':>5}  {'text':>5}  {'arrived':>7}   verdict")

        for length in LENGTHS:
            payload = payload_for(length)
            console.clear()
            try:
                await client.write_gatt_char(
                    WRITE_CHARACTERISTIC, payload, response=response
                )
            except Exception as error:  # the point of the tool is what fails
                print(
                    f"  {len(payload):5}  {length:5}  {'-':>7}   "
                    f"refused by the stack: {type(error).__name__}"
                )
                results.append((len(payload), length, "stack refused"))
                continue

            await asyncio.sleep(1.2)
            printed = NOISE.sub("", console.decode("utf-8", errors="replace"))

            arrived: int | None = None
            for line in printed.splitlines():
                if line.startswith("SHOWN["):
                    arrived = int(line[len("SHOWN[") : line.index("]")])
                elif "write rejected" in line:
                    arrived = -1

            if arrived == length:
                verdict = "ok"
            elif arrived == -1:
                verdict = "rejected by the device"
            elif arrived is None:
                verdict = "vanished: no reaction at all"
            else:
                verdict = f"truncated to {arrived}"
            print(f"  {len(payload):5}  {length:5}  {arrived!s:>7}   {verdict}")
            results.append((len(payload), length, verdict))

    good = [text for _, text, verdict in results if verdict == "ok"]
    print()
    if good:
        print(f"largest text that arrived intact: {max(good)} characters")
    else:
        print("nothing arrived intact")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--address", required=True)
    parser.add_argument(
        "--no-response",
        action="store_true",
        help="use write-without-response, which cannot exceed the MTU",
    )
    args = parser.parse_args()
    return asyncio.run(run(args.address, not args.no_response))


if __name__ == "__main__":
    sys.exit(main())
