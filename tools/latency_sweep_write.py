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

Needs `HA_URL` and `HA_TOKEN` in the environment.
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import json
import os
from pathlib import Path
import statistics
import sys

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

DEFAULT_INTERVALS = (100, 200, 400, 700, 1200, 2000, 4000)
"""Seven points, each about 1.8x the one below it, stopping at 4 s.

Above that the measurement stops being a latency and becomes a failure rate --
at 10 s, three of three first commands were never delivered -- and a mean over
delivered commands would flatter a device nobody could reach."""


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

    connector = aiohttp.TCPConnector(resolver=aiohttp.ThreadedResolver())
    async with aiohttp.ClientSession(connector=connector) as session:
        bus = Bus(session)
        await bus.open()
        try:
            if args.fast_timeout is not None:
                print(
                    f"fast window set to {args.fast_timeout} ms for the sweep",
                    flush=True,
                )
                await set_fast_timeout(config, args.fast_timeout)
            for interval in args.intervals:
                print(f"\n=== {interval} ms ===", flush=True)
                await set_interval(config, interval)

                first, following = [], []
                for _ in range(args.first_reps):
                    print(f"  idling {args.idle:.0f} s ...", flush=True)
                    await asyncio.sleep(args.idle)
                    index += 1
                    got = await command(bus, config, index, args.timeout)
                    report("first", got, interval)
                    first.append(got)

                for _ in range(args.burst):
                    index += 1
                    got = await command(bus, config, index, args.timeout)
                    report("next", got, interval)
                    following.append(got)
                    await asyncio.sleep(args.gap)

                results.append(
                    {"interval_ms": interval, "first": first, "consecutive": following}
                )
                if args.out:
                    write_out(args, config, results)
        finally:
            if args.fast_timeout is not None:
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
    if got.get("failed"):
        print(f"  {case:<6} FAILED (no write acknowledged)", flush=True)
        return
    total = got["total_ms"] / 1000
    print(
        f"  {case:<6} {total:6.2f} s = {got['queued_ms'] / 1000:.2f} queued"
        f" + {got['connect_ms'] / 1000:.2f} connect + {got['write_ms']:.0f} ms write"
        f"   ({total / (interval / 1000):.1f} intervals)",
        flush=True,
    )


def mean_total(samples: list[dict]) -> float:
    usable = [s["total_ms"] / 1000 for s in samples if not s.get("failed")]
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
    parser.add_argument("--idle", type=float, default=32.0)
    parser.add_argument("--gap", type=float, default=1.0)
    parser.add_argument("--timeout", type=float, default=60.0)
    parser.add_argument(
        "--fast-timeout",
        type=int,
        help="shorten the device's fast-advertising window for the sweep, in "
        "milliseconds, and put it back afterwards",
    )
    parser.add_argument("--out")
    args = parser.parse_args()

    if not os.environ.get("HA_TOKEN"):
        raise SystemExit("HA_TOKEN is not set")
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    return asyncio.run(run(args))


if __name__ == "__main__":
    sys.exit(main())
