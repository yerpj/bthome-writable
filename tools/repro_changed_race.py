"""Reproduce what @enaon reported: a read that authenticates and is wrong.

In espruino#8024 on 2026-10-21 he described a three-button lamp whose writable
entries read back intermittently as the wrong object -- `entry 1: read object
0x3C, expected 0x1E`, once `0xEA` -- only when `bw.changed()` runs from a button
handler while the lamp is busy, and cured by deferring the call 250 ms. The
summary he forwarded blames the cost of re-sealing every readable entry. That
explains lateness; it does not explain wrongness, so before anything is changed
in the module this reproduces the shape on our own bench and separates the
variables.

`espruino/bench/many-writables.js` is the device under test: his `setup()`
entry for entry, posted in the same thread -- an advertised battery and three
writable entries all with a `get` -- on a board with nothing on its pins.

This drives it over the
nice!nano's USB console -- the only route, since this host cannot open a GATT
connection to that board -- and reads the verdict out of Home Assistant's own
log, because the symptom is a receiver-side one.

    python -m tools.bench_lock acquire --note "enaon repro"
    .venv-ha/Scripts/python.exe -m tools.repro_changed_race --plain
    .venv-ha/Scripts/python.exe -m tools.repro_changed_race --sealed
    .venv-ha/Scripts/python.exe -m tools.repro_changed_race --sealed --defer 250
    python -m tools.bench_lock release

The conditions are the point. `--plain` takes AES-CCM out of it entirely: if the
symptom appears there, the forwarded diagnosis is wrong and the cause is the
four GATT updates, not the 300 ms of cipher. `--defer 250` is his workaround, so
it has to make the symptom go away or the repro is not his. `--entries` trims
the entry list, which separates "a burst of updates" from "a long burst", and
`--no-fade` replaces his fade with a plain spin, which separates "the thread was
blocked" from "the value kept moving while it was".

Needs `HA_URL` and `HA_TOKEN` in the environment, and the bench lock, because it
writes to a board and changes two Home Assistant settings back and forth.
"""

from __future__ import annotations

import argparse
import asyncio
from dataclasses import dataclass, field
import datetime as dt
import os
from pathlib import Path
import re
import statistics as stats
import sys
import time
from typing import Any

import aiohttp

from tools.devices import DEVICES

SKETCH = "espruino/bench/many-writables.js"
NANO = DEVICES["nano"]
ADDRESS = NANO["address"]
PORT = NANO["port"]

HA_SETTLE_S = 25.0
"""Seconds to let Home Assistant notice a device whose declaration changed.

The entry list and the encryption bit both move when this sketch replaces
whatever the board was running, and the integration adopts that from the
advertising rather than from anything we tell it."""

PRESS_GAP_S = 4.0
"""Default seconds between simulated presses. Each one bumps the settings
revision and the receiver answers that with a connection, so a shorter gap has
the reads queue behind each other -- a condition of its own, and the one a
person pressing a button three times in a row produces."""

SYMPTOM = re.compile(r"read object 0x([0-9A-F]{2}), expected 0x([0-9A-F]{2})")

READABLE = re.compile(r"^(switch|number)\.")
"""Which of this device's entities stand for a readable writable entry.

Its three entries land as two switches and a number. A read that failed leaves
one of them unavailable rather than wrong, so their being live is what makes a
run with no symptom a run where the receiver really did read."""


def now() -> dt.datetime:
    return dt.datetime.now(dt.UTC)


def _base() -> str:
    return os.environ["HA_URL"].rstrip("/")


def _headers() -> dict[str, str]:
    return {"Authorization": "Bearer " + os.environ["HA_TOKEN"]}


async def states(session: aiohttp.ClientSession) -> list[dict[str, Any]]:
    async with session.get(
        f"{_base()}/api/states", headers=_headers(), timeout=30
    ) as response:
        response.raise_for_status()
        return await response.json()


async def ours(session: aiohttp.ClientSession, hint: str) -> dict[str, str]:
    """The entities whose id carries this device's hint, and their states."""
    return {
        row["entity_id"]: row["state"]
        for row in await states(session)
        if hint in row["entity_id"]
    }


# --- the board ---------------------------------------------------------------


def sketch_source(sealed: bool, entries: int) -> str:
    """The sketch, with its two constants set for this condition.

    Substituted rather than parameterised over the console: a condition that is
    chosen at `setup()` time has to be in the file that runs, or the board ends
    up in a state no line of the repro describes.
    """
    source = Path(SKETCH).read_text(encoding="utf-8")
    source = source.replace(
        "var SEALED = true;", f"var SEALED = {str(sealed).lower()};"
    )
    source = source.replace("var ENTRIES = 3;", f"var ENTRIES = {entries};")
    if f"var SEALED = {str(sealed).lower()};" not in source:
        raise SystemExit(f"the SEALED line is not where it was in {SKETCH}")
    if f"var ENTRIES = {entries};" not in source:
        raise SystemExit(f"the ENTRIES line is not where it was in {SKETCH}")
    return source


async def install(sealed: bool, entries: int) -> str:
    from tools.espruino_upload import resolve_modules, upload_serial

    source = resolve_modules(sketch_source(sealed, entries))
    return await upload_serial(PORT, source, save=False, settle=6.0, reset=True)


async def drive(
    presses: int, busy: int, defer: int, gap: float, fade: bool, resetup: int | None
) -> str:
    """Run the presses and come back with what the board printed."""
    from tools.espruino_upload import SerialBoard

    board = SerialBoard(PORT)
    try:
        await board.start()
        await board.send(
            f"bench.busy({busy});bench.defer({defer});"
            f"bench.fade({str(fade).lower()});\n"
        )
        await asyncio.sleep(0.5)
        if resetup is not None:
            await board.send(f"bench.resetup({resetup});\n")
            await asyncio.sleep(2.0)
        await board.send(f"bench.loop({presses}, {int(gap * 1000)});\n")
        await board.listen(presses * gap + 10.0)
        await board.send("bench.stop();bench.report();\n")
        await board.listen(2.0)
        return board.console()
    finally:
        board.close()


# --- the verdict -------------------------------------------------------------


@dataclass
class Outcome:
    condition: str
    presses: int = 0
    changed_ms: list[int] = field(default_factory=list)
    device_errors: list[str] = field(default_factory=list)
    symptoms: list[str] = field(default_factory=list)
    other: list[str] = field(default_factory=list)
    entities: dict[str, str] = field(default_factory=dict)
    reads_seen: int = 0
    connections: int = 0
    readable_live: list[str] = field(default_factory=list)


ANSI = re.compile(r"\x1b\[[0-9;]*[A-Za-z]")
"""Espruino's console redraw, which it emits mid-line.

A printed line arrives as `<esc>[JPRESS[3] ...` often enough that matching on
the start of a line counted three presses out of forty and quietly made the
device-side timings a sample of whatever got through."""


def read_console(text: str, outcome: Outcome) -> None:
    for raw in ANSI.sub("", text).splitlines():
        line = raw.strip()
        if "PRESS[" in line:
            outcome.presses += 1
        elif "CHANGED[" in line:
            parts = line[line.index("CHANGED[") :].split()
            if len(parts) >= 2 and parts[1].isdigit():
                outcome.changed_ms.append(int(parts[1]))
        elif "CONNS=" in line:
            outcome.connections = int(line.split("CONNS=")[1].split()[0])
        elif "ERR " in line and "write rejected" not in line:
            outcome.device_errors.append(line)


def read_log(fresh: list[tuple[str, str, int]], outcome: Outcome) -> None:
    for logger, message, count in fresh:
        if ADDRESS not in message and "bthome_writable" not in logger:
            continue
        line = f"{count}x {logger}: {message}"
        if SYMPTOM.search(message):
            outcome.symptoms.append(line)
        else:
            outcome.other.append(line)


def report(outcome: Outcome) -> int:
    """Print the verdict. 0 ran and concluded, 2 could not conclude."""
    print()
    print(f"=== {outcome.condition} ===")
    print(f"  presses                 {outcome.presses}")
    if outcome.changed_ms:
        median = stats.median(outcome.changed_ms)
        print(
            f"  changed() took          median {median:.0f} ms, "
            f"worst {max(outcome.changed_ms)} ms"
        )
    print(f"  the device complained   {len(outcome.device_errors)}")
    for line in outcome.device_errors[:5]:
        print(f"      {line}")
    print(f"  entities found          {len(outcome.entities)}")
    for entity, value in sorted(outcome.entities.items()):
        print(f"      {entity} = {value}")
    print(f"  the receiver connected      {outcome.connections} times")
    print(f"  state writes seen           {outcome.reads_seen}")
    print("  readable entities live  " + (", ".join(outcome.readable_live) or "(none)"))
    print(f"  WRONG-OBJECT READS      {len(outcome.symptoms)}")
    for line in outcome.symptoms:
        print(f"      {line}")
    print(f"  other new log entries   {len(outcome.other)}")
    for line in outcome.other[:10]:
        print(f"      {line}")
    print()
    if outcome.symptoms:
        print("REPRODUCED: Home Assistant read an object it did not ask for")
        return 0
    if not (outcome.reads_seen or outcome.connections):
        print(
            "INCONCLUSIVE: Home Assistant did not both hear and read this device, "
            "so a clean run proves nothing"
        )
        return 2
    print("NOT REPRODUCED in this condition")
    return 0


# --- the run -----------------------------------------------------------------


async def run(args: argparse.Namespace) -> int:
    from tools.chain_test import Watch, new_entries, system_log
    from tools.ha_bench import bench_prepared
    from tools.latency_sweep_write import Bus

    sealed = not args.plain
    condition = (
        f"{'sealed' if sealed else 'plaintext'}, {args.entries} entries, "
        f"busy {args.busy} ms, defer {args.defer} ms, "
        f"{'spin' if args.no_fade else 'fade'}, {args.gap:g} s apart"
        + (f", re-setup to {args.resetup}" if args.resetup else "")
    )
    outcome = Outcome(condition=condition)

    if not args.no_install:
        print(f"installing {SKETCH} on {PORT} ({'sealed' if sealed else 'plaintext'})")
        console = await install(sealed, args.entries)
        for line in console.splitlines():
            if line.startswith(("advertising as", "writable entries", "service data")):
                print(f"  {line}")
            if line.startswith(("Uncaught", "ERROR:")):
                print(f"  {line}", file=sys.stderr)
                return 2

    connector = aiohttp.TCPConnector(resolver=aiohttp.ThreadedResolver())
    async with (
        aiohttp.ClientSession(connector=connector) as session,
        bench_prepared(session) as changed,
    ):
        for line in changed:
            print(f"  {line}")
        print(f"letting Home Assistant settle for {HA_SETTLE_S:.0f} s ...")
        await asyncio.sleep(HA_SETTLE_S)

        bus = Bus(session)
        await bus.open()
        try:
            before = await system_log(bus)
            # Only the ones that are live: this device has accumulated entities
            # from every sketch it has ever run, and the dead ones never update.
            live = [
                entity
                for entity, value in (await ours(session, args.hint)).items()
                if READABLE.search(entity) and value not in ("unavailable",)
            ]
            print(
                f"driving {args.presses} presses, {args.gap:g} s apart ...",
                flush=True,
            )
            started = time.monotonic()
            async with Watch(session, live) as watch:
                since = now()
                console = await drive(
                    args.presses,
                    args.busy,
                    args.defer,
                    args.gap,
                    not args.no_fade,
                    args.resetup,
                )
                read_console(console, outcome)
                print(f"  the board ran for {time.monotonic() - started:.0f} s")
                # The receiver answers a moved revision with a connection, and
                # the last one is still in flight when the board stops.
                await asyncio.sleep(20.0)
                # Every successful read-all writes each entity's state, whether
                # or not the value moved, so this counts reads rather than
                # changes -- which is the only way a run with no symptom can be
                # told apart from a run where nothing was read at all.
                outcome.reads_seen = max(
                    (len(watch.arrivals(entity, since)) for entity in live), default=0
                )

            outcome.entities = await ours(session, args.hint)
            # A readable entry whose value Home Assistant holds is a read that
            # worked; one it could not read goes unavailable, which is how a
            # silent failure shows up here, as an absence rather than a wrong
            # value.
            outcome.readable_live = [
                entity
                for entity, value in outcome.entities.items()
                if READABLE.search(entity) and value not in ("unavailable", "unknown")
            ]
            read_log(new_entries(before, await system_log(bus)), outcome)
        finally:
            await bus.close()

    if args.console:
        print("\n=== board console ===")
        print(console.strip() or "(nothing)")
    return report(outcome)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument(
        "--sealed", action="store_true", help="with a bindkey (the default)"
    )
    mode.add_argument(
        "--plain",
        action="store_true",
        help="no bindkey: takes AES-CCM out of the experiment",
    )
    parser.add_argument("--entries", type=int, default=3, choices=[1, 2, 3])
    parser.add_argument(
        "--no-fade",
        action="store_true",
        help="busy-wait instead of running the simulated fade, so the value "
        "the third entry reports holds still while the thread is blocked",
    )
    parser.add_argument(
        "--busy",
        type=int,
        default=150,
        help="milliseconds the simulated handler blocks the thread before "
        "calling changed() (default 150)",
    )
    parser.add_argument(
        "--defer",
        type=int,
        default=0,
        help="milliseconds to defer changed() by; 0 calls it inline, which is "
        "what @enaon's lamp did (his workaround was 250)",
    )
    parser.add_argument("--presses", type=int, default=20)
    parser.add_argument(
        "--resetup",
        type=int,
        choices=[1, 2, 3],
        help="re-run setup() with this many writable entries on the live device "
        "just before driving, which is what adding an entry while developing "
        "does to a receiver that has cached the GATT table",
    )
    parser.add_argument(
        "--gap",
        type=float,
        default=PRESS_GAP_S,
        help=f"seconds between presses (default {PRESS_GAP_S:.0f})",
    )
    parser.add_argument(
        "--hint",
        default="b216",
        help="substring of this device's entity ids in Home Assistant",
    )
    parser.add_argument(
        "--no-install",
        action="store_true",
        help="drive the sketch already running rather than sending it again",
    )
    parser.add_argument(
        "--console", action="store_true", help="print everything the board said"
    )
    args = parser.parse_args()
    if "HA_TOKEN" not in os.environ or "HA_URL" not in os.environ:
        print("set HA_URL and HA_TOKEN first (docs/shared-bench.md)", file=sys.stderr)
        return 2
    return asyncio.run(run(args))


if __name__ == "__main__":
    sys.exit(main())
