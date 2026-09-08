"""Upload JavaScript to an Espruino board over Bluetooth, from the host.

The Espruino Web IDE does this over Web Bluetooth; this does the same thing from
a terminal, so the hardware-test loop does not need a human with a browser for
every iteration.

    python -m tools.espruino_upload --address C8:80:32:AD:F7:B9 \
        espruino/dist/single-light-standalone.min.js

What the IDE does that a naive "write the file to the UART" does not:

* interrupts whatever is running first, and stops its timers;
* resolves `require("...")` before sending, because a board has no network --
  the IDE injects each module with `Modules.addCached`, and so does this;
* honours Espruino's XON/XOFF flow control, because the board's input buffer is
  a couple of hundred bytes and a BLE link will happily outrun it.
"""

from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path
import re
import sys
import urllib.request

from bleak import BleakClient, BleakScanner

# Espruino speaks the Nordic UART Service.
UART_SERVICE = "6e400001-b5a3-f393-e0a9-e50e24dcca9e"
UART_RX = "6e400002-b5a3-f393-e0a9-e50e24dcca9e"  # host -> board
UART_TX = "6e400003-b5a3-f393-e0a9-e50e24dcca9e"  # board -> host

XON = 0x11
XOFF = 0x13
CTRL_C = b"\x03"

MODULE_URL = "https://www.espruino.com/modules/{name}.js"
MODULE_CACHE = Path(__file__).resolve().parent.parent / ".module-cache"

# Anything the board must be told to stop doing before new code lands.
PREAMBLE = "clearInterval();clearWatch();\n"

# The console buffers one statement at a time and truncates it well before a
# module fits, so injected modules are assembled from pieces this size.
MODULE_CHUNK = 512


class Board:
    """A connected Espruino, with flow control and console capture."""

    def __init__(
        self, client: BleakClient, chunk: int = 20, response: bool = True
    ) -> None:
        self.client = client
        self.chunk = chunk
        self.response = response
        self.output = bytearray()
        self._flowing = asyncio.Event()
        self._flowing.set()

    def _on_notify(self, _sender: object, data: bytearray) -> None:
        for byte in data:
            if byte == XOFF:
                self._flowing.clear()
            elif byte == XON:
                self._flowing.set()
            else:
                self.output.append(byte)

    async def start(self) -> None:
        await self.client.start_notify(UART_TX, self._on_notify)

    async def send(self, text: str) -> None:
        """Write text to the board, pausing whenever it says to.

        Written *with* response by default. Espruino asserts XOFF once its input
        buffer is nearly full, but over BLE that signal arrives at least one
        connection event late, and a stream of unacknowledged writes will have
        overrun the buffer by then -- which shows up as a syntax error in the
        middle of a large paste, from a `}` that never arrived.
        """
        payload = text.encode("utf-8", errors="replace")
        for offset in range(0, len(payload), self.chunk):
            await asyncio.wait_for(self._flowing.wait(), timeout=30)
            await self.client.write_gatt_char(
                UART_RX,
                payload[offset : offset + self.chunk],
                response=self.response,
            )
            if not self.response:
                await asyncio.sleep(0.012)

    async def interrupt(self) -> None:
        await self.client.write_gatt_char(UART_RX, CTRL_C, response=False)
        await asyncio.sleep(0.3)

    def console(self) -> str:
        return self.output.decode("utf-8", errors="replace")


def fetch_module(name: str) -> str:
    """The module source, from espruino.com, cached on disk."""
    MODULE_CACHE.mkdir(exist_ok=True)
    cached = MODULE_CACHE / f"{name}.js"
    if cached.exists():
        return cached.read_text(encoding="utf-8")

    with urllib.request.urlopen(MODULE_URL.format(name=name), timeout=30) as response:
        source = response.read().decode("utf-8")
    cached.write_text(source, encoding="utf-8", newline="")
    return source


def resolve_modules(source: str) -> str:
    """Inject every `require`d module, the way the Web IDE does.

    A board has no way to fetch anything, so an unresolved require() is a
    runtime error several seconds after upload, which is a confusing place to
    discover a typo.
    """
    names = sorted(set(re.findall(r"""require\(\s*["']([\w.-]+)["']\s*\)""", source)))
    if not names:
        return source

    preamble = []
    for name in names:
        module = fetch_module(name)
        # Assembled from pieces rather than one string literal: the Espruino
        # console buffers one statement at a time and truncates it well before a
        # whole module fits, which surfaces as a syntax error pointing at a line
        # nowhere near the real problem. Each += is its own small statement.
        # json.dumps escapes correctly, including the template literals inside.
        preamble.append("var _m = '';")
        for offset in range(0, len(module), MODULE_CHUNK):
            preamble.append(
                f"_m += {json.dumps(module[offset : offset + MODULE_CHUNK])};"
            )
        preamble.append(f"Modules.addCached({json.dumps(name)}, _m);")
        preamble.append("_m = undefined;")
        print(f"  resolved require({name!r}) - {len(module)} bytes")
    return "\n".join(preamble) + "\n" + source


async def find_address(name_hint: str | None) -> str:
    print("scanning for an Espruino board ...")
    devices = await BleakScanner.discover(timeout=8.0, return_adv=True)
    candidates = [
        (address, adv)
        for address, (_device, adv) in devices.items()
        if UART_SERVICE in [u.lower() for u in adv.service_uuids]
        or (adv.local_name or "").lower().startswith(("puck", "espruino", "mdbt"))
    ]
    if name_hint:
        candidates = [
            entry for entry in candidates if name_hint.lower() in str(entry[1]).lower()
        ]
    if not candidates:
        raise SystemExit("no Espruino board found — is it in range and powered?")
    for address, adv in candidates:
        print(f"  {address}  {adv.local_name}  rssi={adv.rssi}")
    return candidates[0][0]


async def upload(
    address: str, source: str, save: bool, settle: float, response: bool = True
) -> str:
    print(f"connecting to {address} ...")
    async with BleakClient(address, timeout=30.0) as client:
        board = Board(
            client, chunk=max(20, (client.mtu_size or 23) - 3), response=response
        )
        await board.start()
        print(f"connected, MTU {client.mtu_size}, chunk {board.chunk}")

        await board.interrupt()
        board.output.clear()
        await board.send(PREAMBLE)
        await asyncio.sleep(0.3)

        print(f"sending {len(source)} bytes ...")
        await board.send(source)
        if not source.endswith("\n"):
            await board.send("\n")

        if save:
            await asyncio.sleep(0.5)
            print("saving to flash ...")
            await board.send("save();\n")

        await asyncio.sleep(settle)
        return board.console()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("file", type=Path, help="JavaScript file to upload")
    parser.add_argument("--address", help="BLE address; scans if omitted")
    parser.add_argument("--name", help="substring to pick a board when scanning")
    parser.add_argument(
        "--save",
        action="store_true",
        help="save() after upload so the code survives a power cycle",
    )
    parser.add_argument(
        "--no-response",
        action="store_true",
        help="write without acknowledgement: faster, but drops bytes on long uploads",
    )
    parser.add_argument(
        "--settle",
        type=float,
        default=3.0,
        help="seconds to keep listening to the console after upload",
    )
    args = parser.parse_args()

    source = args.file.read_text(encoding="utf-8")
    print(f"{args.file}: {len(source)} bytes")
    source = resolve_modules(source)

    address = args.address or asyncio.run(find_address(args.name))
    console = asyncio.run(
        upload(address, source, args.save, args.settle, not args.no_response)
    )

    print("\n=== board console ===")
    print(console.strip() or "(nothing)")

    # The console echoes everything we sent, and our own source contains the
    # word "error" many times over, so match what Espruino actually prints when
    # something goes wrong rather than anything that looks alarming.
    failures = [
        line
        for line in console.splitlines()
        if line.startswith(("Uncaught", "ERROR:")) or "Execution Interrupted" in line
    ]
    if failures:
        print("\nthe board reported:", file=sys.stderr)
        for line in failures:
            print(f"  {line}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
