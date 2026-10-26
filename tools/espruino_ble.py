"""Send a sketch to a board over the radio, from here, and read what it says.

The Web IDE does this over Web Bluetooth and it is the right tool when a human
is in front of it. It is the wrong tool for a measurement: the board under the
meter has to be loaded, verified and let go of on a schedule, and the thing
being measured is the connection, so every second of console costs a figure.

    python -m tools.espruino_ble --address C8:80:32:AD:F7:B9 \
        --eval "process.env.VERSION" --eval "process.env.MODULES"
    python -m tools.espruino_ble --address C8:80:32:AD:F7:B9 \
        --load espruino/dist/power-arms-standalone.min.js \
        --eval "typeof bench" --expect 120000

Nothing is written to flash: the code lands in RAM and dies with the next power
cycle, which is what `docs/shared-bench.md` requires of a bench board.

**The console prompt is the flow control.** A console over the Nordic UART
service has none of its own, and writing a 23 kB bundle as fast as Bluetooth
will carry it overruns the input buffer: the board answers
`FIFO_FULL,LOW_MEMORY,MEMORY`, a line arrives truncated, and the sketch that
comes up is not the one that was sent. The echo is no help, because Espruino
echoes a character from the interrupt that received it, long before anything
executes it: waiting for the echo overran the buffer exactly as fast as waiting
for nothing. The prompt is the signal. Espruino writes one when it has finished
a line, so a block of k lines goes out and the sender waits for k more prompts.

**And it goes out pretokenised.** `E.setFlags({pretokenise: 1})` makes Espruino
store a function as tokens rather than as its source text, which on a Puck.js
is the difference between a bundle that fits in RAM and one that does not.

**A load is verified or it is nothing.** A sketch that arrived in part leaves a
board that advertises, answers and measures wrong, so `--expect` fails the
command when the answer is not the one given, and any FIFO or memory complaint
on the console fails it too. An eighteen-minute recording is worth one round
trip.

A connection is a write on a shared bench: take the lock first.
"""

from __future__ import annotations

import argparse
import asyncio
from pathlib import Path
import sys
import time

from bleak import BleakClient, BleakScanner

UART_RX = "6e400002-b5a3-f393-e0a9-e50e24dcca9e"
UART_TX = "6e400003-b5a3-f393-e0a9-e50e24dcca9e"
CHUNK = 50
"""Bytes a write. The Nordic UART service takes MTU minus three and Espruino's
console consumes it as it arrives; 50 is what `hold_link` already uses and it
leaves the chunking well inside every negotiated MTU."""
BLOCK = 256
"""Bytes between flow-control waits, cut at a line boundary."""


def chunks(data: bytes, size: int = CHUNK) -> list[bytes]:
    """The payload as the writes it will be sent in."""
    if size < 1:
        raise ValueError("a chunk is at least one byte")
    return [data[offset : offset + size] for offset in range(0, len(data), size)]


def blocks(source: str, size: int = BLOCK) -> list[str]:
    """The source cut into flow-controlled blocks, never mid-line.

    A line is the unit Espruino executes, so a block ending inside one leaves
    the interpreter holding an unfinished statement while the sender waits for
    an echo that cannot arrive until the rest of it does.
    """
    out: list[str] = []
    current = ""
    for line in source.splitlines(keepends=True):
        if current and len(current) + len(line) > size:
            out.append(current)
            current = ""
        current += line
    if current:
        out.append(current)
    return out


def answers(output: str) -> list[str]:
    """What the interpreter said, without its prompts and echoes.

    Espruino answers an expression with `=value`, which is the one line worth
    keeping: everything else on the console is a prompt, an echo of what was
    sent, or a `console.log` from the sketch itself.
    """
    return [
        line[1:].strip()
        for line in output.replace("\r", "\n").split("\n")
        if line.startswith("=")
    ]


def complaints(output: str) -> list[str]:
    """The lines that mean the load did not survive the trip."""
    return [
        line.strip()
        for line in output.replace("\r", "\n").split("\n")
        if "FIFO_FULL" in line or "MEMORY" in line or "Uncaught" in line
    ]


async def _write(client: BleakClient, text: str) -> None:
    for chunk in chunks(text.encode()):
        await client.write_gatt_char(UART_RX, chunk, response=True)


def prompts(seen: bytes) -> int:
    """How many lines the console says it has finished.

    Espruino ends a line with a newline and then writes its prompt, and
    minified code never begins a line with `>`, so this counts executions
    rather than echoes.
    """
    return seen.count(b"\n>")


async def _send_source(
    client: BleakClient, source: str, seen: bytearray, patience: float
) -> tuple[int, int]:
    """Write the source, one block at a time, paced by the console prompt."""
    stalled = 0
    parts = blocks(source)
    for block in parts:
        wanted = prompts(seen) + block.count("\n")
        await _write(client, block)
        deadline = time.monotonic() + patience
        while prompts(seen) < wanted:
            if time.monotonic() > deadline:
                stalled += 1
                break
            await asyncio.sleep(0.02)
    return len(parts), stalled


async def run(
    address: str,
    load: Path | None,
    evals: list[str],
    expect: list[str],
    settle: float,
    hold: float,
    raw: bool = False,
    pretokenise: bool = True,
    patience: float = 4.0,
) -> int:
    device = await BleakScanner.find_device_by_address(address, timeout=40.0)
    if device is None:
        print(f"{address}: not seen", file=sys.stderr)
        return 1

    seen = bytearray()

    def arrived(_: object, data: bytearray) -> None:
        seen.extend(data)

    async with BleakClient(
        device, timeout=30.0, winrt={"use_cached_services": False}
    ) as client:
        started = time.monotonic()
        print(f"connected to {address}")
        await client.start_notify(UART_TX, arrived)
        await _write(client, "\x03")
        await asyncio.sleep(0.4)

        if load is not None:
            if pretokenise:
                await _write(client, "E.setFlags({pretokenise: 1});\n")
                await asyncio.sleep(0.4)
            source = load.read_text(encoding="utf-8")
            if not source.endswith("\n"):
                source += "\n"
            sending = time.monotonic()
            parts, stalled = await _send_source(client, source, seen, patience)
            print(
                f"sent {len(source)} bytes in {parts} blocks,"
                f" {time.monotonic() - sending:.1f} s"
                + (f", {stalled} stalled" if stalled else "")
            )
            await asyncio.sleep(settle)

        said = len(seen)
        for expression in evals:
            await _write(client, expression.rstrip("\n") + "\n")
            await asyncio.sleep(1.2)
        if hold:
            print(f"holding the link for {hold:.0f} s")
            await asyncio.sleep(hold)
        print(f"disconnecting after {time.monotonic() - started:.1f} s")

    text = seen.decode("utf-8", "replace")
    if raw:
        print("--- console, verbatim ---")
        print(text.strip())
    trouble = complaints(text)
    replies = answers(text[said:])
    print("--- answers ---")
    for index, expression in enumerate(evals):
        reply = replies[index] if index < len(replies) else "(no answer)"
        print(f"  {expression}  ->  {reply}")
    if trouble:
        print("--- the board complained ---", file=sys.stderr)
        for line in trouble:
            print(f"  {line}", file=sys.stderr)
    for wanted in expect:
        if not any(wanted in reply for reply in replies):
            print(f"FAILED: nothing answered {wanted!r}", file=sys.stderr)
            return 2
    return 3 if trouble else 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--address", required=True)
    parser.add_argument("--load", type=Path, help="a file to send to the console")
    parser.add_argument(
        "--eval", action="append", default=[], help="an expression, repeatable"
    )
    parser.add_argument(
        "--expect",
        action="append",
        default=[],
        help="text one of the answers must contain, or the command fails",
    )
    parser.add_argument(
        "--settle",
        type=float,
        default=3.0,
        help="seconds to wait after the load before asking anything",
    )
    parser.add_argument(
        "--patience",
        type=float,
        default=4.0,
        help="seconds to wait for one block's echo before pressing on",
    )
    parser.add_argument(
        "--no-pretokenise",
        action="store_true",
        help="store function source as text, which a Puck.js has no room for",
    )
    parser.add_argument(
        "--raw", action="store_true", help="print the whole console verbatim"
    )
    parser.add_argument(
        "--hold",
        type=float,
        default=0.0,
        help="seconds to keep the link open after the last answer",
    )
    args = parser.parse_args(argv)
    if not args.load and not args.eval:
        raise SystemExit("give --load, --eval, or both")
    return asyncio.run(
        run(
            args.address,
            args.load,
            args.eval,
            args.expect,
            args.settle,
            args.hold,
            args.raw,
            not args.no_pretokenise,
            args.patience,
        )
    )


if __name__ == "__main__":
    sys.exit(main())
