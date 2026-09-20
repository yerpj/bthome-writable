"""Time a command from Home Assistant to the device's write acknowledgement.

This is the boundary that matters to a receiver and to a user: the command
arrives, Home Assistant catches the device advertising, connects, writes, and
the device acknowledges. It excludes everything afterwards — the refreshed
advertising, the sensor that reflects the effect, the entity update — which is
what the other two sweeps measure and which made their numbers larger and
noisier than the question deserved.

No witness on the device is needed, because Home Assistant knows all four
timestamps itself: the integration fires `bthome_writable_write` after each
acknowledged write with `queued_ms`, `connect_ms`, `write_ms` and `total_ms`.
This tool subscribes to that event over the WebSocket API, issues commands, and
collects what comes back.

    python -m tools.latency_sweep_write --device puck --out docs/data/write-puck.json

The expectation worth testing: a first command after a quiet period should cost
one to two advertising intervals, because a central cannot begin a connection
until it catches an advertising event.

Each first command is issued after the idle wait plus a random fraction of one
advertising interval. Without that, every sample would be taken at the same
phase of the device's advertising train, and the phase is precisely what
determines how long the receiver waits to catch it.

Needs `HA_URL` and `HA_TOKEN` in the environment.
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import json
import os
from pathlib import Path
import random
import statistics
import sys
import time

import aiohttp

DEVICES = {
    "puck": {
        "address": "C8:80:32:AD:F7:B9",
        "label": "Puck.js switch (light), command to write acknowledged",
        "entity": "switch.bureau_mobilesensf7b9_light",
        "kind": "switch",
    },
    "nano": {
        "address": "CD:F5:77:3A:B2:16",
        "label": "nice!nano text (OLED), command to write acknowledged",
        "entity": "text.espruino_b216_text",
        "kind": "text",
        "port": "COM15",
    },
}

DEFAULT_INTERVALS = (100, 200, 400, 800, 1600, 3200, 5000)
"""Seven points, each about twice the one below it, stopping at 5 s.

Above that the measurement stops being a latency and becomes a failure rate --
at 10 s, three of three first commands were never delivered -- and a mean over
delivered commands would flatter a device nobody could reach."""

FAST_WINDOW_MARGIN = 3.0
"""Seconds of slack demanded between the fast window closing and the next first
command. The device's timer, the receiver's scan and this host's clock are three
different clocks; a first command taken a hair early would be a fast-advertising
sample wearing an idle label."""


class Bus:
    """One WebSocket connection: fire commands, collect the timing events."""

    def __init__(self, session: aiohttp.ClientSession) -> None:
        self.session = session
        self.ws: aiohttp.ClientWebSocketResponse | None = None
        self.timings: asyncio.Queue = asyncio.Queue()
        self._id = 0
        self._pending: dict[int, asyncio.Future] = {}
        self._reader: asyncio.Task | None = None

    async def open(self) -> None:
        url = os.environ["HA_URL"].rstrip("/").replace("http://", "ws://")
        self.ws = await self.session.ws_connect(url + "/api/websocket")
        await self.ws.receive_json()
        await self.ws.send_json(
            {"type": "auth", "access_token": os.environ["HA_TOKEN"]}
        )
        if (await self.ws.receive_json()).get("type") != "auth_ok":
            raise SystemExit("Home Assistant refused the token")
        self._reader = asyncio.create_task(self._read())
        await self.command(
            {"type": "subscribe_events", "event_type": "bthome_writable_write"}
        )

    async def _read(self) -> None:
        assert self.ws is not None
        async for message in self.ws:
            if message.type is not aiohttp.WSMsgType.TEXT:
                continue
            payload = message.json()
            if payload.get("type") == "event":
                self.timings.put_nowait(payload["event"]["data"])
            elif payload.get("type") == "result":
                future = self._pending.pop(payload.get("id"), None)
                if future is not None and not future.done():
                    future.set_result(payload)

    async def command(self, payload: dict) -> dict:
        assert self.ws is not None
        self._id += 1
        mine = self._id
        future: asyncio.Future = asyncio.get_running_loop().create_future()
        self._pending[mine] = future
        await self.ws.send_json({"id": mine, **payload})
        return await asyncio.wait_for(future, 60)

    async def call_service(self, domain: str, service: str, data: dict) -> None:
        await self.command(
            {
                "type": "call_service",
                "domain": domain,
                "service": service,
                "service_data": data,
            }
        )

    async def close(self) -> None:
        if self._reader is not None:
            self._reader.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._reader
        if self.ws is not None:
            await self.ws.close()


class FastWindow:
    """Which side of the device's fast window each sample was taken on.

    After any connection the device advertises at `fastInterval` for
    `fastTimeout`, then drops back to the interval under test (D-024). The two
    cases this sweep separates are exactly the two sides of that window, so
    mislabelling one as the other is the one error that would make the whole
    table meaningless -- a "first" command taken while the device is still fast
    measures the fast interval, not the one in the column header.

    Rather than trust the arithmetic of idle waits, every connection to the
    device is stamped here, including the ones that set the interval, and every
    sample carries how long the device had been left alone when it was issued.
    A sample on the wrong side of the window is flagged and left out of the
    summary rather than quietly averaged in.
    """

    def __init__(self, fast_timeout_ms: int) -> None:
        self.seconds = fast_timeout_ms / 1000
        self.last_contact = time.monotonic()

    def touched(self) -> None:
        """Something connected to the device: the window has just reopened."""
        self.last_contact = time.monotonic()

    def idle_for(self) -> float:
        """How long the device has been left alone, as of now.

        Read when the command is issued, never after it comes back: a command
        that takes ten seconds would otherwise charge its own duration to the
        idle time and look like a first command.
        """
        return time.monotonic() - self.last_contact

    def classify(self, case: str, idle_for: float) -> dict:
        device_idle = idle_for >= self.seconds
        wanted_idle = case == "first"
        return {
            "idle_for_s": round(idle_for, 2),
            "device_idle": device_idle,
            "fast_window_ok": device_idle == wanted_idle,
        }


async def command(bus: Bus, config: dict, index: int, timeout: float) -> dict:
    """One command, and the timing the integration reports for it."""
    while not bus.timings.empty():  # anything left over belongs to an earlier command
        bus.timings.get_nowait()

    if config["kind"] == "switch":
        await bus.call_service(
            "switch",
            "turn_on" if index % 2 == 0 else "turn_off",
            {"entity_id": config["entity"]},
        )
    else:
        await bus.call_service(
            "text",
            "set_value",
            {"entity_id": config["entity"], "value": f"sweep {index:04d}"},
        )

    try:
        return await asyncio.wait_for(bus.timings.get(), timeout)
    except TimeoutError:
        return {"failed": True}


async def set_fast_timeout(config: dict, ms: int) -> None:
    """Shorten the window the device stays fast in after a disconnect.

    Every sample of a first command has to wait that window out, so the module's
    30 s default turns a ten-sample interval into eight minutes of waiting. The
    measurement itself is unaffected: what it times is a command issued while the
    device is back on its idle interval, and this only changes how long it takes
    to get there. Put back at the end of the sweep.
    """
    await run_on_device(config, f"bw.setFastTimeout({ms});")


async def run_on_device(config: dict, statement: str) -> None:
    """Run one statement on the sketch, over USB where there is a cable.

    Ctrl-C first, so a console left mid-line does not swallow it.
    """
    if config.get("port"):
        import serial

        with serial.Serial(config["port"], 115200, timeout=0.2) as link:
            link.write((chr(3) + statement + chr(10)).encode())
            await asyncio.sleep(1.0)
            link.reset_input_buffer()
        return

    from bleak import BleakClient, BleakScanner

    device = await BleakScanner.find_device_by_address(config["address"], timeout=60)
    if device is None:
        raise SystemExit(f"{config['address']}: not seen")
    async with BleakClient(device, timeout=30.0) as client:
        line = (statement + chr(10)).encode()
        for offset in range(0, len(line), 50):
            await client.write_gatt_char(
                "6e400002-b5a3-f393-e0a9-e50e24dcca9e",
                line[offset : offset + 50],
                response=True,
            )
        await asyncio.sleep(1.0)


async def set_interval(config: dict, ms: int, attempts: int = 4) -> None:
    """Put the device on the interval about to be measured, or give up loudly.

    Worth the fuss: `set_adv_interval` reports a device it could not reach by
    returning non-zero, and a sweep that ignored that would quietly measure the
    previous interval and label it with this one.
    """
    if config.get("port"):
        from tools.latency_sweep import set_interval_serial

        set_interval_serial(config["port"], ms)
        return
    from tools.set_adv_interval import run as set_run

    for attempt in range(1, attempts + 1):
        try:
            if await set_run(config["address"], ms, False) == 0:
                return
            why = "device not reached"
        except Exception as error:  # a host that cannot connect raises, too
            why = f"{type(error).__name__}: {error}"
        print(
            f"  could not set {ms} ms ({why}) -- attempt {attempt}/{attempts}",
            flush=True,
        )
        await asyncio.sleep(5)
    raise SystemExit(f"{config['address']}: could not set the interval to {ms} ms")


async def run(args) -> int:
    config = DEVICES[args.device]
    results: list[dict] = []
    index = 0
    window = FastWindow(args.fast_timeout)

    connector = aiohttp.TCPConnector(resolver=aiohttp.ThreadedResolver())
    async with aiohttp.ClientSession(connector=connector) as session:
        bus = Bus(session)
        await bus.open()
        try:
            print(
                f"fast window set to {args.fast_timeout} ms for the sweep; "
                f"a first command waits {args.idle:.0f} s + jitter after the last "
                "connection, a following one goes out inside the window",
                flush=True,
            )
            await set_fast_timeout(config, args.fast_timeout)
            window.touched()
            for interval in args.intervals:
                print(f"\n=== {interval} ms ===", flush=True)
                await set_interval(config, interval)
                window.touched()

                first, following = [], []
                for _ in range(args.first_reps):
                    # A fixed wait would issue every command at the same phase of
                    # the device's advertising train, and the thing being measured
                    # is how long it takes to catch one of those. Spreading the
                    # wait over a whole interval samples the phase uniformly
                    # instead of sampling one point of it ten times.
                    jitter = random.uniform(0, interval / 1000)
                    print(
                        f"  idling {args.idle:.0f} s + {jitter * 1000:.0f} ms ...",
                        flush=True,
                    )
                    await asyncio.sleep(args.idle + jitter)
                    index += 1
                    idle_for = window.idle_for()
                    got = await command(bus, config, index, args.timeout)
                    got |= window.classify("first", idle_for)
                    # The window reopens when this command's link closes, which
                    # is now: the device starts counting fastTimeout down from
                    # the disconnect, not from the connect.
                    window.touched()
                    report("first", got, interval)
                    first.append(got)

                for _ in range(args.burst):
                    index += 1
                    idle_for = window.idle_for()
                    got = await command(bus, config, index, args.timeout)
                    got |= window.classify("next", idle_for)
                    # The window reopens when this command's link closes, which
                    # is now: the device starts counting fastTimeout down from
                    # the disconnect, not from the connect.
                    window.touched()
                    report("next", got, interval)
                    following.append(got)
                    # Jittered too, so a burst cannot fall into lockstep with the
                    # receiver's own write debounce.
                    await asyncio.sleep(args.gap + random.uniform(0, 0.25))

                results.append(
                    {"interval_ms": interval, "first": first, "consecutive": following}
                )
                if args.out:
                    write_out(args, config, results)
        finally:
            with contextlib.suppress(Exception):
                await set_fast_timeout(config, 30000)
                print("fast window restored to 30000 ms", flush=True)
            await bus.close()

    for row in results:
        print(
            f"{row['interval_ms']:6} ms   first {mean_total(row['first']):6.2f} s"
            f"   following {mean_total(row['consecutive']):5.2f} s"
        )
    return 0


def report(case: str, got: dict, interval: int) -> None:
    where = (
        "" if got.get("fast_window_ok", True) else "  << WRONG SIDE OF THE FAST WINDOW"
    )
    if got.get("failed"):
        print(f"  {case:<6} FAILED (no write acknowledged){where}", flush=True)
        return
    total = got["total_ms"] / 1000
    print(
        f"  {case:<6} {total:6.2f} s = {got['queued_ms'] / 1000:.2f} queued"
        f" + {got['connect_ms'] / 1000:.2f} connect + {got['write_ms']:.0f} ms write"
        f"   ({total / (interval / 1000):.1f} intervals)"
        f"   [idle {got.get('idle_for_s', 0):.1f} s]{where}",
        flush=True,
    )


def usable_totals(samples: list[dict]) -> list[float]:
    """Delivered, and taken on the side of the fast window it was labelled with."""
    return [
        s["total_ms"] / 1000
        for s in samples
        if not s.get("failed") and s.get("fast_window_ok", True)
    ]


def mean_total(samples: list[dict]) -> float:
    usable = usable_totals(samples)
    return statistics.fmean(usable) if usable else 0.0


def write_out(args, config: dict, results: list[dict]) -> None:
    path = Path(args.out)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "address": config["address"],
                "label": config["label"],
                "entity": config["entity"],
                "measures": "Home Assistant command to the device's GATT write "
                "acknowledgement, as the integration times it",
                "idle_wait_s": args.idle,
                "fast_timeout_ms": args.fast_timeout,
                "fast_window_note": "Every sample carries idle_for_s, the time "
                "since anything last connected to the device, and device_idle, "
                "whether that exceeds fast_timeout_ms. A first command is only "
                "counted when the device had fallen back to the interval under "
                "test; a following one only when it had not.",
                "results": results,
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--device", choices=tuple(DEVICES), required=True)
    parser.add_argument(
        "--intervals", type=int, nargs="+", default=list(DEFAULT_INTERVALS)
    )
    parser.add_argument("--first-reps", type=int, default=10)
    parser.add_argument("--burst", type=int, default=8)
    parser.add_argument("--idle", type=float, default=12.0)
    parser.add_argument("--gap", type=float, default=1.0)
    parser.add_argument("--timeout", type=float, default=60.0)
    parser.add_argument(
        "--fast-timeout",
        type=int,
        default=8000,
        help="the device's fast-advertising window during the sweep, in "
        "milliseconds, put back to 30000 afterwards. Long enough that a burst "
        "stays inside it, short enough that waiting it out between first "
        "commands does not dominate the campaign",
    )
    parser.add_argument("--out")
    args = parser.parse_args()

    # The two ends of the sweep sit on opposite sides of the fast window, so the
    # window has to be shorter than the idle wait and longer than a burst gap.
    # Getting either wrong silently relabels samples, which is worse than
    # stopping.
    fast = args.fast_timeout / 1000
    if args.idle < fast + FAST_WINDOW_MARGIN:
        raise SystemExit(
            f"--idle {args.idle:.0f} s leaves no margin after a {fast:.0f} s fast "
            f"window; use at least {fast + FAST_WINDOW_MARGIN:.0f} s"
        )
    if args.gap >= fast:
        raise SystemExit(
            f"--gap {args.gap:.1f} s is not inside a {fast:.0f} s fast window, so "
            "a following command would be a first command with another name"
        )

    if not os.environ.get("HA_TOKEN"):
        raise SystemExit("HA_TOKEN is not set")
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    return asyncio.run(run(args))


if __name__ == "__main__":
    sys.exit(main())
