"""Measure response time against the device's advertising interval.

The question this answers is the one every battery device has to settle: how
much does a slow advertising interval cost the user? A central can only *begin*
a connection when it catches a connectable advertising event, so the interval
bounds how long the first command waits. After a disconnect the module
advertises fast (`fastInterval`, 100 ms) for `fastTimeout` (30 s), so commands
that follow one another do not pay that price — and the point of the sweep is to
show the two curves apart rather than argue about them.

    python -m tools.latency_sweep --address C8:80:32:AD:F7:B9 --kind switch \
        --out docs/data/latency-puck-switch.json

For each interval the tool measures:

- **first** — a command issued after the device has been left alone for longer
  than `fastTimeout`, so it is advertising at its idle interval. Repeated
  `--first-reps` times, each preceded by the full idle wait.
- **consecutive** — `--burst` commands issued back to back straight afterwards,
  each its own connect-write-disconnect, while the device is still advertising
  fast.

Each measurement is split into the time to establish the link and the time the
write itself took, because only the first is expected to move.

Read it as *this host's* numbers: connection setup on a Windows/WinRT adapter is
slower than on BlueZ, and that offset is in every figure here (D-047).
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import json
from pathlib import Path
import statistics
import sys
import time

from bleak import BleakClient, BleakScanner

from tools.ha_protocol import characteristic_uuid

UART_RX = "6e400002-b5a3-f393-e0a9-e50e24dcca9e"
UART_TX = "6e400003-b5a3-f393-e0a9-e50e24dcca9e"

DEFAULT_INTERVALS = (100, 200, 500, 1000, 2000, 5000, 10000)


def payloads(kind: str) -> list[bytes]:
    """Two writes that differ, so the device really does something each time."""
    if kind == "switch":
        return [bytes.fromhex("1e01"), bytes.fromhex("1e00")]
    if kind == "text":
        return [
            bytes([0x53, len(body)]) + body
            for body in (b"sweep A 1234", b"sweep B 5678")
        ]
    raise SystemExit(f"unknown kind: {kind}")


def set_interval_serial(port: str, ms: int) -> None:
    """Set the interval over USB, for a board that has a cable.

    Preferred wherever one exists: an Espruino moves its console to USB when a
    cable is plugged in, and its BLE console then answers unreliably — which is
    how the first run of this sweep against the nice!nano died.
    """
    import serial

    with serial.Serial(port, 115200, timeout=0.2) as link:
        link.write(f"\x03bw.setAdvertisingInterval({ms});\n".encode())
        time.sleep(1.0)
        link.reset_input_buffer()


async def set_interval(address: str, ms: int, attempts: int = 3) -> None:
    """Ask the sketch to change its idle interval, over its BLE console."""
    for attempt in range(1, attempts + 1):
        try:
            device = await BleakScanner.find_device_by_address(address, timeout=60.0)
            if device is None:
                raise TimeoutError(f"{address}: not seen")
            async with BleakClient(device, timeout=30.0) as client:
                await client.start_notify(UART_TX, lambda _s, _d: None)
                line = f"bw.setAdvertisingInterval({ms});\n".encode()
                for offset in range(0, len(line), 50):
                    await client.write_gatt_char(
                        UART_RX, line[offset : offset + 50], response=True
                    )
                await asyncio.sleep(1.0)
            return
        except Exception as error:  # a console that does not answer is not fatal
            print(f"  setting the interval failed ({error}); retrying", flush=True)
            if attempt == attempts:
                raise
            await asyncio.sleep(5)


async def catch(address: str, timeout: float):
    """Wait for one advertising event from the device, and return it.

    Timed as part of the response, because it *is* part of it: a central cannot
    begin a connection until it catches a connectable advertisement, and that
    wait is the whole of what the interval changes. Connecting by address
    without this is also unreliable on WinRT, which answers "device not found"
    the moment its own cache has gone cold -- at a 10 s interval, every time.
    """
    wanted = address.upper()
    loop = asyncio.get_running_loop()
    found: asyncio.Future = loop.create_future()

    def seen(device, _advertisement) -> None:
        if device.address.upper() == wanted and not found.done():
            found.set_result(device)

    async with BleakScanner(seen):
        try:
            return await asyncio.wait_for(asyncio.shield(found), timeout)
        except TimeoutError:
            return None


async def one_write(
    address: str, entry: int, payload: bytes, attempts: int = 3
) -> dict:
    """One command, timed in three phases, with the retries it needed."""
    started = time.perf_counter()
    failures = 0
    for _attempt in range(attempts):
        device = await catch(address, timeout=60.0)
        if device is None:
            failures += 1
            continue
        caught = time.perf_counter()
        client = BleakClient(device, timeout=60.0)
        try:
            await client.connect()
        except Exception:  # a missed connection costs another advertising event
            failures += 1
            with contextlib.suppress(Exception):
                await client.disconnect()
            continue
        connected = time.perf_counter()
        try:
            await client.write_gatt_char(
                characteristic_uuid(entry), payload, response=True
            )
            written = time.perf_counter()
        finally:
            with contextlib.suppress(Exception):
                await client.disconnect()
        return {
            "discover": caught - started,
            "connect": connected - caught,
            "write": written - connected,
            "retries": failures,
        }
    return {
        "discover": 0.0,
        "connect": 0.0,
        "write": 0.0,
        "retries": failures,
        "failed": True,
        "gave_up_after": time.perf_counter() - started,
    }


async def run(args) -> int:
    values = payloads(args.kind)
    results: list[dict] = []

    for index, interval in enumerate(args.intervals):
        print(f"\n=== {interval} ms ===", flush=True)
        if args.serial:
            set_interval_serial(args.serial, interval)
        else:
            await set_interval(args.address, interval)

        first: list[dict] = []
        for rep in range(args.first_reps):
            # Wait out fastTimeout, so the device really is at its idle
            # interval. Without this the whole sweep measures the fast mode.
            print(f"  idling {args.idle:.0f} s ...", flush=True)
            await asyncio.sleep(args.idle)
            sample = await one_write(
                args.address, args.entry, values[rep % len(values)]
            )
            report("first", sample)
            first.append(sample)

        consecutive: list[dict] = []
        for rep in range(args.burst):
            sample = await one_write(
                args.address, args.entry, values[rep % len(values)]
            )
            report("next", sample)
            consecutive.append(sample)
            await asyncio.sleep(args.gap)

        results.append(
            {"interval_ms": interval, "first": first, "consecutive": consecutive}
        )
        if args.out:
            write_out(args, results)
        if index < len(args.intervals) - 1:
            print("  (settling before the next interval)", flush=True)
            await asyncio.sleep(2)

    for row in results:
        print(
            f"{row['interval_ms']:6} ms   first "
            f"{mean_total(row['first']):5.2f} s   consecutive "
            f"{mean_total(row['consecutive']):5.2f} s"
        )
    return 0


def report(case: str, sample: dict) -> None:
    if sample.get("failed"):
        print(
            f"  {case:<9} FAILED after {sample['gave_up_after']:.0f} s "
            f"and {sample['retries']} attempts",
            flush=True,
        )
        return
    print(
        f"  {case:<9} {total(sample):6.2f} s  (catch {sample['discover']:.2f}, "
        f"connect {sample['connect']:.2f}, retries {sample['retries']})",
        flush=True,
    )


def total(sample: dict) -> float:
    return sample["discover"] + sample["connect"] + sample["write"]


def mean_total(samples: list[dict]) -> float:
    usable = [total(s) for s in samples if not s.get("failed")]
    return statistics.fmean(usable) if usable else 0.0


def write_out(args, results: list[dict]) -> None:
    path = Path(args.out)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "address": args.address,
                "kind": args.kind,
                "entry": args.entry,
                "label": args.label or args.kind,
                "idle_wait_s": args.idle,
                "host": "Windows/WinRT bench host",
                "results": results,
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--address", required=True)
    parser.add_argument("--kind", choices=("switch", "text"), required=True)
    parser.add_argument("--entry", type=int, default=1)
    parser.add_argument("--label", help="how the device is named in the output")
    parser.add_argument(
        "--intervals",
        type=int,
        nargs="+",
        default=list(DEFAULT_INTERVALS),
        help="advertising intervals to sweep, in milliseconds",
    )
    parser.add_argument("--first-reps", type=int, default=3)
    parser.add_argument("--burst", type=int, default=5)
    parser.add_argument(
        "--idle",
        type=float,
        default=35.0,
        help="seconds to leave the device alone before a 'first' write; must "
        "exceed its fastTimeout (30 s by default)",
    )
    parser.add_argument("--gap", type=float, default=1.0)
    parser.add_argument(
        "--serial",
        help="set the interval over this serial port (e.g. COM15) rather than "
        "over BLE — use it whenever the board has a USB cable",
    )
    parser.add_argument("--out", help="write the samples here as JSON")
    args = parser.parse_args()
    return asyncio.run(run(args))


if __name__ == "__main__":
    sys.exit(main())
