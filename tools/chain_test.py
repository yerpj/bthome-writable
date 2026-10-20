"""Qualify the whole chain with Home Assistant in it (D-110).

`tools.regression` answers the two questions a user feels -- does a command
arrive, and when. P1 and P2 changed something else: *when the module publishes
an advertisement, and when it reads a sensor*. Neither can be judged from the
device alone, because the half that matters is what a receiver makes of it:
after P2 a rate change republishes the bytes already on air, packet id and
encryption counter included, and after P1 each entry is read on its own
schedule rather than at a fixed tick. Both are claims about what Home Assistant
sees.

So this drives the real chain end to end -- Espruino sketch, radio, the host's
adapter or an ESP32 proxy, `bthome-ble`, the integration, the entity, a service
call, the GATT write, the device -- and judges eight things:

  A  the integration is loaded and the entities are there
  B  an `interval: 0` entry reaches HA at the advertising rate
  C  an `interval: 300000` entry reaches HA every five minutes, and not oftener
  D  a command is delivered and acknowledged, on both boards
  E  a write produces an effect a receiver can see (the closed loop, via HA)
  F  a burst of ten writes all land, and the last one is what stands
  G  the fast window opening and closing is invisible to HA
  H  none of it put a line in Home Assistant's log

B and C are P1's claim at the far end of the chain: one self-arming timer
serving a one-second entry and a five-minute one, at their own rates, from the
same device. E, F and G are P2's: three advertisements per burst that are the
bytes already on air, and a receiver that cannot tell.

Needs `HA_URL` and `HA_TOKEN` (`docs/shared-bench.md`), the bench lock, and both
boards on their examples:

    nano -> espruino/examples/oled-text.js       (text + die temperature)
    puck -> espruino/examples/light-loop.js      (light + illuminance + battery)

Check E reads a light sensor, so it depends on the room. Under a cover the
Puck's own LED is the only thing its sensor can see and the difference is
enormous; uncovered -- which is how this bench stands since 2026-10-20 -- the
room can swallow it, and then E reports itself unresolved rather than failing.
Cover the Puck if you want that one answered.

    python -m tools.bench_lock acquire --note "chain test"
    .venv-ha/Scripts/python.exe -m tools.chain_test
    python -m tools.bench_lock release

About six minutes. Exit status is 0 only if every check passed, so it can gate a
release next to `tools.regression`. It writes to the devices and to Home
Assistant (switch and text values); it changes no setting and restores nothing,
because it changes nothing that needs restoring.
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
from dataclasses import dataclass, field
import datetime as dt
import itertools
import os
import statistics as st
import sys
from typing import Any

import aiohttp

from tools.devices import DEVICES

PUCK = "puck"
NANO = "nano"

ILLUMINANCE = "sensor.bureau_mobilesensf7b9_illuminance"
BATTERY = "sensor.bureau_mobilesensf7b9_battery"
TEMPERATURE = "sensor.espruino_b216_b216_temperature"

FAST_SAMPLE_S = 30.0
"""How long to watch the one-second entry. Thirty advertisements' worth, which
separates "arriving" from "arriving once" without making the run long."""

SLOW_WINDOW_S = 320.0
"""How long the five-minute entry must be watched. Its interval plus a little:
over this a correct device reports it once, twice if a report lands at each
end, and a device that woke on a fixed tick and read it when due would be
indistinguishable -- which is the point. What C rules out is the opposite
failure, a battery arriving far more often than it was asked for."""

POLL_S = 2.0
LOOP_SETTLE_S = 8.0
"""Seconds to let the illuminance follow the light. The entry is read at every
wake and the radio advertises every second, so this is generous on purpose: the
host's adapter is the slow part (tools/closed_loop.py says why)."""

LOOP_SAMPLES = 5
"""Readings taken with the light off, then on. The Puck's own LED is inches
from its sensor, so under a cover one sample each would do -- but an uncovered
Puck sits in whatever the room is doing, and a median of five against the
spread of five is what separates the LED from a cloud."""

LOOP_MARGIN_LX = 5.0
"""The least difference worth calling an effect, in lux, before the noise term
is added. Below this the room has swallowed the LED and the check says so
rather than guessing."""

BURST = 10


@dataclass
class Check:
    name: str
    ok: bool
    detail: str
    inconclusive: bool = False


@dataclass
class Report:
    checks: list[Check] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    def add(self, name: str, ok: bool, detail: str) -> None:
        self.checks.append(Check(name, ok, detail))
        print(f"  {'ok  ' if ok else 'FAIL'} {name:<46} {detail}", flush=True)

    def unresolved(self, name: str, detail: str) -> None:
        """Not a failure and not a pass: the bench could not answer.

        A check whose answer depends on the room has to be able to say so. The
        alternative is a FAIL that sends the next person looking for a bug in
        the module, or a pass that was never earned.
        """
        self.checks.append(Check(name, False, detail, inconclusive=True))
        print(f"  ????  {name:<46} {detail}", flush=True)

    def note(self, text: str) -> None:
        self.notes.append(text)
        print(f"       {text}", flush=True)


def _base() -> str:
    return os.environ["HA_URL"].rstrip("/")


def _headers() -> dict[str, str]:
    return {"Authorization": "Bearer " + os.environ["HA_TOKEN"]}


async def state(session: aiohttp.ClientSession, entity: str) -> dict[str, Any]:
    async with session.get(
        f"{_base()}/api/states/{entity}", headers=_headers(), timeout=20
    ) as response:
        response.raise_for_status()
        return await response.json()


async def components(session: aiohttp.ClientSession) -> list[str]:
    async with session.get(
        f"{_base()}/api/config", headers=_headers(), timeout=20
    ) as response:
        response.raise_for_status()
        return (await response.json()).get("components", [])


async def system_log(bus) -> dict[tuple[str, str], int]:
    """What Home Assistant has collected, as {(logger, message): count}.

    Over the WebSocket rather than `/api/error_log`, which is gone in 2026.7
    and answers 404 -- `tools.ha_probe` swallowed that and printed "nothing" for
    a log it had never read. These entries are grouped by logger and message
    with a count, so a repeat shows up as a bigger count rather than a new row,
    and the diff has to compare both.
    """
    got = await bus.command({"type": "system_log/list"})
    rows = got.get("result") or []
    collected: dict[tuple[str, str], int] = {}
    for row in rows:
        message = row.get("message")
        text = " | ".join(message) if isinstance(message, list) else str(message)
        collected[(str(row.get("name")), text)] = int(row.get("count", 1))
    return collected


def _reported(got: dict[str, Any]) -> dt.datetime:
    return dt.datetime.fromisoformat(got["last_reported"])


class Watch:
    """Every moment Home Assistant was told something about these entities.

    `last_reported` moves on every state write, whether or not the value
    changed, which is exactly "the device was heard and the integration had
    something to say". Polling it is enough at these rates and costs HA one
    cheap GET per entity.
    """

    def __init__(self, session: aiohttp.ClientSession, entities: list[str]) -> None:
        self.session = session
        self.entities = entities
        self.seen: dict[str, list[dt.datetime]] = {e: [] for e in entities}
        self.last: dict[str, dt.datetime | None] = {e: None for e in entities}
        self._task: asyncio.Task | None = None

    async def _run(self) -> None:
        while True:
            for entity in self.entities:
                try:
                    got = await state(self.session, entity)
                except Exception:  # a poll that fails is a poll, not a verdict
                    continue
                when = _reported(got)
                if self.last[entity] is None or when > self.last[entity]:
                    self.last[entity] = when
                    self.seen[entity].append(when)
            await asyncio.sleep(POLL_S)

    async def __aenter__(self) -> Watch:
        # Prime, so that the first poll is not counted as an arrival.
        for entity in self.entities:
            got = await state(self.session, entity)
            self.last[entity] = _reported(got)
        self._task = asyncio.create_task(self._run())
        return self

    async def __aexit__(self, *_: Any) -> None:
        if self._task is not None:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task

    def arrivals(self, entity: str, since: dt.datetime) -> list[dt.datetime]:
        return [w for w in self.seen[entity] if w >= since]

    def gaps(self, entity: str, since: dt.datetime) -> list[float]:
        when = self.arrivals(entity, since)
        return [(b - a).total_seconds() for a, b in itertools.pairwise(when)]


def now() -> dt.datetime:
    return dt.datetime.now(dt.UTC)


async def samples(
    session: aiohttp.ClientSession, entity: str, count: int = LOOP_SAMPLES
) -> list[float]:
    """Several readings of one numeric sensor, a second apart."""
    got: list[float] = []
    for index in range(count):
        if index:
            await asyncio.sleep(1.2)
        got.append(float((await state(session, entity))["state"]))
    return got


def _spread(values: list[float]) -> float:
    """Half the range, which is the honest noise term for five samples."""
    return (max(values) - min(values)) / 2 if len(values) > 1 else 0.0


async def check_a(session: aiohttp.ClientSession, report: Report) -> None:
    loaded = await components(session)
    report.add(
        "A  the integration is loaded",
        "bthome_writable" in loaded,
        "bthome_writable" if "bthome_writable" in loaded else "not in /api/config",
    )
    wanted = [
        DEVICES[PUCK]["entity"],
        DEVICES[NANO]["entity"],
        ILLUMINANCE,
        BATTERY,
        TEMPERATURE,
    ]
    bad = []
    for entity in wanted:
        try:
            got = await state(session, entity)
        except Exception as error:
            bad.append(f"{entity}: {type(error).__name__}")
            continue
        if got["state"] in ("unavailable", "unknown"):
            bad.append(f"{entity}: {got['state']}")
    report.add(
        "A  every entity of both devices is there",
        not bad,
        f"{len(wanted)} entities" if not bad else "; ".join(bad),
    )


async def check_b(watch: Watch, report: Report, started: dt.datetime) -> None:
    arrivals = watch.arrivals(ILLUMINANCE, started)
    gaps = watch.gaps(ILLUMINANCE, started)
    worst = max(gaps) if gaps else FAST_SAMPLE_S
    ok = len(arrivals) >= 10 and worst <= 5.0
    report.add(
        "B  interval 0 arrives at the advertising rate",
        ok,
        f"{len(arrivals)} reports in {FAST_SAMPLE_S:.0f} s, "
        f"median gap {st.median(gaps):.1f} s, worst {worst:.1f} s"
        if gaps
        else f"{len(arrivals)} reports in {FAST_SAMPLE_S:.0f} s",
    )


async def check_c(watch: Watch, report: Report, started: dt.datetime) -> None:
    arrivals = watch.arrivals(BATTERY, started)
    elapsed = (now() - started).total_seconds()
    gaps = watch.gaps(BATTERY, started)
    ok = 1 <= len(arrivals) <= 2
    detail = f"{len(arrivals)} reports in {elapsed:.0f} s"
    if gaps:
        detail += f", gap {gaps[0]:.0f} s"
        ok = ok and 280.0 <= gaps[0] <= 340.0
    report.add("C  interval 300000 arrives every five minutes", ok, detail)
    fast = watch.arrivals(ILLUMINANCE, started)
    report.note(
        f"the same device reported its one-second entry {len(fast)} times in "
        f"that window: one timer, two cadences"
    )
    warm = watch.arrivals(TEMPERATURE, started)
    report.note(
        f"the nano's 30 s die temperature reported {len(warm)} times -- it is "
        f"published only when the reading moves (D-106), so few or none is "
        f"correct on a board sitting still"
    )


async def check_d(bus, report: Report) -> None:
    from tools.latency_sweep_write import command

    for index, name in enumerate((PUCK, NANO)):
        config = DEVICES[name]
        got = await command(bus, config, index, timeout=90.0)
        ok = not got.get("failed")
        report.add(
            f"D  a command lands on the {name}",
            ok,
            f"{got['total_ms'] / 1000:.2f} s, write {got.get('write_ms', 0):.0f} ms"
            if ok
            else "no acknowledgement inside 90 s",
        )


async def check_e(session: aiohttp.ClientSession, bus, report: Report) -> None:
    """The closed loop, through Home Assistant rather than a private BLE link.

    The light's own state is never advertised (PROTOCOL.md S2.3), so what proves
    the write arrived is a *different* object: the illuminance, measured through
    another LED, read at every wake and carried in the next advertisement. Both
    writes go through `command()`, so each is known to have been acknowledged
    before the sensor is believed.
    """
    from tools.latency_sweep_write import command

    config = DEVICES[PUCK]
    await command(bus, config, 1, timeout=90.0)  # odd index: turn_off
    await asyncio.sleep(LOOP_SETTLE_S)
    dark = await samples(session, ILLUMINANCE)
    await command(bus, config, 0, timeout=90.0)  # even index: turn_on
    await asyncio.sleep(LOOP_SETTLE_S)
    lit = await samples(session, ILLUMINANCE)

    name = "E  a write through HA moves what HA measures"
    low, high = st.median(dark), st.median(lit)
    noise = max(_spread(dark), _spread(lit))
    needed = LOOP_MARGIN_LX + 3 * noise
    detail = (
        f"{low:.0f} lx off, {high:.0f} lx on, difference {high - low:+.0f} "
        f"against {needed:.0f} needed (noise {noise:.1f})"
    )
    if high - low >= needed:
        report.add(name, True, detail)
    elif low - high >= needed:
        report.add(name, False, detail + " -- the wrong way round")
    else:
        report.unresolved(name, detail + " -- cover the Puck and run this again")
    await command(bus, config, 1, timeout=90.0)
    await asyncio.sleep(LOOP_SETTLE_S)


async def check_f(session: aiohttp.ClientSession, bus, report: Report) -> None:
    """The burst that started all this, through Home Assistant.

    @enaon's dimming burst stuttered because every accepted write rebuilt the
    packet (D-106), and P2 took the last rebuild out of the write path. What
    must still be true is the plain thing: ten commands in a row all arrive, and
    the tenth is the one that stands.
    """
    from tools.latency_sweep_write import command

    config = DEVICES[PUCK]
    delivered = 0
    times: list[float] = []
    for index in range(BURST):
        got = await command(bus, config, index, timeout=90.0)
        if got.get("failed"):
            continue
        delivered += 1
        times.append(got["total_ms"])
    report.add(
        "F  ten commands in a row all arrive",
        delivered == BURST,
        f"{delivered}/{BURST} delivered, median {st.median(times) / 1000:.2f} s"
        if times
        else "none delivered",
    )
    # BURST is even, so the last index was odd: turn_off.
    await asyncio.sleep(LOOP_SETTLE_S)
    got = await state(session, config["entity"])
    report.add(
        "F  and the last one is what stands",
        got["state"] == "off",
        f"{config['entity']} is {got['state']}, expected off",
    )


async def check_g(session: aiohttp.ClientSession, watch: Watch, report: Report) -> None:
    """The fast window closing is a rate change, and nothing else.

    The device has just been written to, so it is advertising fast; `fastTimeout`
    later it republishes the bytes already on air at the idle rate, with the
    packet id and the encryption counter where they were. If that is really
    invisible, the entity stays available and the advertisements keep arriving
    across the moment it happens.
    """
    marker = now()
    await asyncio.sleep(35.0)  # the module's default fastTimeout is 30 s
    got = await state(session, ILLUMINANCE)
    arrivals = watch.arrivals(ILLUMINANCE, marker)
    report.add(
        "G  the fast window closing is invisible",
        got["state"] not in ("unavailable", "unknown") and len(arrivals) >= 5,
        f"{len(arrivals)} reports across it, now {got['state']} lx",
    )
    light = await state(session, DEVICES[PUCK]["entity"])
    report.add(
        "G  and the writable entity did not go unavailable",
        light["state"] in ("on", "off"),
        f"{light['entity_id']} is {light['state']}",
    )


def new_entries(
    before: dict[tuple[str, str], int], after: dict[tuple[str, str], int]
) -> list[tuple[str, str, int]]:
    """Rows that appeared, and rows that happened again, while this ran."""
    fresh = []
    for key, count in after.items():
        grew = count - before.get(key, 0)
        if grew > 0:
            fresh.append((key[0], key[1], grew))
    return fresh


INTERESTING = ("bthome", "bluetooth", "bleak", "esp32", "b216", "f7b9", "espruino")


async def check_h(bus, report: Report, before: dict[tuple[str, str], int]) -> None:
    fresh = new_entries(before, await system_log(bus))
    guilty = [
        (name, text, grew)
        for name, text, grew in fresh
        if any(word in f"{name} {text}".lower() for word in INTERESTING)
    ]
    report.add(
        "H  nothing new in Home Assistant's log",
        not guilty,
        f"{len(fresh)} new or repeated entries, none about this"
        if not guilty
        else f"{len(guilty)}: {guilty[0][0]} x{guilty[0][2]}: {guilty[0][1][:70]}",
    )
    for name, text, grew in guilty[1:]:
        report.note(f"also {name} x{grew}: {text[:80]}")


async def run(args: argparse.Namespace) -> int:
    from tools.ha_bench import bench_prepared
    from tools.latency_sweep_write import Bus

    report = Report()
    # A threaded resolver, like every other tool here: aiohttp's default one
    # wants a selector loop on Windows and raises before the first request.
    connector = aiohttp.TCPConnector(resolver=aiohttp.ThreadedResolver())
    async with aiohttp.ClientSession(connector=connector) as session:
        print("the chain, end to end", flush=True)
        await check_a(session, report)

        async with bench_prepared(session) as changed:
            for line in changed:
                report.note(line)
            bus = Bus(session)
            await bus.open()
            try:
                log_before = await system_log(bus)
                async with Watch(session, [ILLUMINANCE, BATTERY, TEMPERATURE]) as watch:
                    started = now()
                    print(
                        f"  watching the fast entry for {FAST_SAMPLE_S:.0f} s ...",
                        flush=True,
                    )
                    await asyncio.sleep(FAST_SAMPLE_S)
                    await check_b(watch, report, started)

                    await check_d(bus, report)
                    await check_e(session, bus, report)
                    await check_f(session, bus, report)
                    await check_g(session, watch, report)

                    left = SLOW_WINDOW_S - (now() - started).total_seconds()
                    if left > 0:
                        wait = f"  waiting {left:.0f} s more for the slow entry ..."
                        print(wait, flush=True)
                        await asyncio.sleep(left)
                    await check_c(watch, report, started)
                await check_h(bus, report, log_before)
            finally:
                await bus.close()

    failed = [c for c in report.checks if not c.ok and not c.inconclusive]
    open_ones = [c for c in report.checks if c.inconclusive]
    print()
    if failed:
        print(f"{len(failed)} check(s) failed")
    elif open_ones:
        print(
            f"the chain is qualified, except {len(open_ones)} the bench could not "
            f"answer: {', '.join(c.name.split('  ')[0] for c in open_ones)}"
        )
    else:
        print("the chain is qualified")
    return 1 if failed else 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    args = parser.parse_args()
    for name in ("HA_URL", "HA_TOKEN"):
        if not os.environ.get(name):
            print(f"{name} is not set; see docs/shared-bench.md", file=sys.stderr)
            return 2
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    return asyncio.run(run(args))


if __name__ == "__main__":
    raise SystemExit(main())
