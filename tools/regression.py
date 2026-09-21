"""Guard the two things a user actually feels: does a command arrive, and when.

Every other suite in this repo checks bytes and branches. Nothing checked that a
command still *lands*, or still lands as quickly as it did last week -- and the
changes that moved those numbers most (the batching, its debounce, the retry
policy, the write counter) all passed every test while doing it. This runs a
short campaign against the real devices and compares it with a recorded
baseline.

    python -m tools.regression                   # check both devices
    python -m tools.regression --device puck     # one of them
    python -m tools.regression --update-baseline # record a new baseline

Exit status is 0 when nothing regressed and 1 when something did, so it can gate
a release. It takes about three minutes per device.

**What it does to the bench**, and restores afterwards: disables the ESP32 proxy
and the OLED automation (`ha_bench`), sets the advertising interval under test,
and shortens the device's fast-advertising window. Take the bench lock first --
`python -m tools.bench_lock acquire` -- as for any other measurement.

**What it deliberately does not do:** fail on a single slow sample. The spread
of a first command is wide by nature (D-060) and the medians of two runs of ten
moved 30-50 % against each other (D-061), so the thresholds below are generous
and the sample counts are the smallest that still separate a change from the
noise. A guard that cries wolf is a guard that gets disabled.
"""

from __future__ import annotations

import argparse
import asyncio
from dataclasses import dataclass
import json
import os
from pathlib import Path
import statistics as st
import subprocess
import sys
import time

from tools.devices import DEVICES

# `aiohttp`, and everything that reaches for it, is imported where it is used.
# The two functions that decide whether a release goes out -- `compare` and
# `summarise` -- are pure, and the suite that tests them runs in the tools
# virtualenv, which has no Home Assistant in it and should not need one.

BASELINE = Path("docs/data/regression-baseline.json")

INTERVAL_MS = 1000
"""The advertising interval every run uses.

One interval, not a ladder: the ladder is a study (D-060), this is a guard. A
second is what the examples ship with and what a device is most likely to sit
at, and it is short enough that a run costs minutes rather than an hour."""

FIRST_REPS = 8
REPEAT_REPS = 16
FAST_TIMEOUT_MS = 8000
IDLE_S = 12.0
GAP_S = 1.0
RETRY_FLOOR_S = 25.0
"""Above this a connection was retried rather than merely slow: the pooled
distribution of D-061 is empty between 19.4 s and 30.5 s."""


@dataclass(frozen=True)
class Check:
    """One comparison, and enough of its arithmetic to argue with."""

    name: str
    baseline: float
    measured: float
    limit: float
    worse_is_higher: bool
    verdict: str  # "ok", "regressed", or "suspicious"
    note: str = ""

    @property
    def failed(self) -> bool:
        return self.verdict == "regressed"


def _slower(name: str, base: float, got: float, factor: float, floor: float) -> Check:
    """A latency may grow by `factor`, plus `floor` for the small end.

    The floor matters more than it looks: without it a baseline of 0.30 s would
    be guarded to within 0.18 s, which is inside the sample-to-sample spread of
    a repeated command (D-062) and would fail on nothing.
    """
    limit = base * factor + floor
    if got > limit:
        return Check(name, base, got, limit, True, "regressed")
    if base > 0 and got < base / 3 and got + floor < base:
        return Check(
            name,
            base,
            got,
            limit,
            True,
            "suspicious",
            "far faster than the baseline -- has the bench changed? "
            "A proxy reusing a link does exactly this (D-054)",
        )
    return Check(name, base, got, limit, True, "ok")


def _fraction(name: str, base: float, got: float, slack: float) -> Check:
    """A delivered fraction may fall by `slack` before it counts."""
    limit = base - slack
    verdict = "regressed" if got < limit else "ok"
    return Check(name, base, got, limit, False, verdict)


def compare(baseline: dict, measured: dict) -> list[Check]:
    """The whole policy, in one readable place.

    Kept pure so it can be tested without a radio, and so that changing a
    threshold is a reviewable diff rather than a number buried in a run.
    """
    return [
        _slower(
            "first command, median",
            baseline["first_median_s"],
            measured["first_median_s"],
            factor=1.6,
            floor=0.30,
        ),
        _slower(
            "first command, 90th percentile",
            baseline["first_p90_s"],
            measured["first_p90_s"],
            factor=2.0,
            floor=0.50,
        ),
        _slower(
            "repeated command, median",
            baseline["repeat_median_s"],
            measured["repeat_median_s"],
            factor=1.6,
            floor=0.15,
        ),
        _slower(
            "repeated command, 90th percentile",
            baseline["repeat_p90_s"],
            measured["repeat_p90_s"],
            factor=2.0,
            floor=0.30,
        ),
        _slower(
            "the write itself, median ms",
            baseline["write_median_ms"],
            measured["write_median_ms"],
            factor=2.0,
            floor=20.0,
        ),
        _fraction(
            "delivered",
            baseline["delivered_fraction"],
            measured["delivered_fraction"],
            slack=0.10,
        ),
        _fraction(
            "connected without a retry",
            baseline["direct_fraction"],
            measured["direct_fraction"],
            slack=0.20,
        ),
    ]


def summarise(first: list[dict], repeat: list[dict]) -> dict:
    """Turn one run's samples into the handful of numbers the baseline holds."""
    delivered = [s for s in first + repeat if not s.get("failed")]
    usable = [s for s in delivered if s.get("fast_window_ok", True)]
    mislabelled = len(delivered) - len(usable)

    def totals(samples: list[dict]) -> list[float]:
        return sorted(
            s["total_ms"] / 1000
            for s in samples
            if not s.get("failed") and s.get("fast_window_ok", True)
        )

    def p90(values: list[float]) -> float:
        return values[min(len(values) - 1, int(0.9 * len(values)))] if values else 0.0

    first_t, repeat_t = totals(first), totals(repeat)
    direct = [s for s in usable if s["connect_ms"] / 1000 < RETRY_FLOOR_S]
    return {
        "commands": len(first) + len(repeat),
        "delivered_fraction": round(
            len(delivered) / max(1, len(first) + len(repeat)), 3
        ),
        "direct_fraction": round(len(direct) / max(1, len(usable)), 3),
        "first_median_s": round(st.median(first_t), 3) if first_t else 0.0,
        "first_p90_s": round(p90(first_t), 3),
        "repeat_median_s": round(st.median(repeat_t), 3) if repeat_t else 0.0,
        "repeat_p90_s": round(p90(repeat_t), 3),
        "write_median_ms": round(st.median([s["write_ms"] for s in usable]), 1)
        if usable
        else 0.0,
        "samples_on_the_wrong_side_of_the_fast_window": mislabelled,
    }


async def measure(bus, config: dict, index: int) -> dict:
    """One device's run: first commands after a quiet period, then a burst."""
    from tools.latency_sweep_write import (
        FastWindow,
        command,
        set_fast_timeout,
        set_interval,
    )

    window = FastWindow(FAST_TIMEOUT_MS)
    await set_fast_timeout(config, FAST_TIMEOUT_MS)
    window.touched()
    await set_interval(config, INTERVAL_MS)
    window.touched()

    first: list[dict] = []
    for _ in range(FIRST_REPS):
        await asyncio.sleep(IDLE_S)
        index += 1
        idle_for = window.idle_for()
        got = await command(bus, config, index, timeout=60.0)
        got |= window.classify("first", idle_for)
        window.touched()
        first.append(got)
        print(f"  first  {_line(got)}", flush=True)

    repeat: list[dict] = []
    for _ in range(REPEAT_REPS):
        index += 1
        idle_for = window.idle_for()
        got = await command(bus, config, index, timeout=60.0)
        got |= window.classify("next", idle_for)
        window.touched()
        repeat.append(got)
        print(f"  repeat {_line(got)}", flush=True)
        await asyncio.sleep(GAP_S)

    return {"first": first, "repeat": repeat, "index": index}


def _line(got: dict) -> str:
    if got.get("failed"):
        return "FAILED"
    flag = (
        "" if got.get("fast_window_ok", True) else "  << wrong side of the fast window"
    )
    return f"{got['total_ms'] / 1000:5.2f} s{flag}"


def _commit() -> str:
    try:
        return subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()
    except Exception:
        return "unknown"


def render(device: str, checks: list[Check]) -> None:
    print(f"\n{device}")
    for check in checks:
        mark = {"ok": "ok  ", "regressed": "FAIL", "suspicious": "hm  "}[check.verdict]
        print(
            f"  {mark} {check.name:<34} baseline {check.baseline:>8.3f}"
            f"   now {check.measured:>8.3f}   limit {check.limit:>8.3f}"
        )
        if check.note:
            print(f"       {check.note}")


async def run(args) -> int:
    devices = [args.device] if args.device else list(DEVICES)
    baseline = (
        json.loads(BASELINE.read_text(encoding="utf-8")) if BASELINE.exists() else {}
    )
    if not baseline and not args.update_baseline:
        raise SystemExit(f"no baseline at {BASELINE}; run with --update-baseline first")

    import aiohttp

    from tools.ha_bench import bench_prepared
    from tools.latency_sweep_write import Bus, set_fast_timeout

    results: dict[str, dict] = {}
    failed = False
    connector = aiohttp.TCPConnector(resolver=aiohttp.ThreadedResolver())
    async with (
        aiohttp.ClientSession(connector=connector) as session,
        bench_prepared(session) as changed,
    ):
        print("bench: " + ("; ".join(changed) or "already as wanted"), flush=True)
        bus = Bus(session)
        await bus.open()
        try:
            for name in devices:
                config = DEVICES[name]
                print(f"\n=== {name} at {INTERVAL_MS} ms ===", flush=True)
                try:
                    run_result = await measure(bus, config, index=0)
                    results[name] = summarise(run_result["first"], run_result["repeat"])
                finally:
                    with_suppressed = set_fast_timeout(config, 30000)
                    try:
                        await with_suppressed
                    except Exception as error:  # the bench matters more
                        print(f"  could not restore the fast window: {error}")
        finally:
            await bus.close()

    for name, measured in results.items():
        stale = measured["samples_on_the_wrong_side_of_the_fast_window"]
        if stale:
            print(f"\n{name}: {stale} sample(s) on the wrong side of the fast window")
            print("  the run is not comparable; not judged as a regression")
            failed = True
            continue
        if args.update_baseline or name not in baseline.get("devices", {}):
            continue
        checks = compare(baseline["devices"][name], measured)
        render(name, checks)
        failed = failed or any(check.failed for check in checks)

    if args.update_baseline:
        BASELINE.write_text(
            json.dumps(
                {
                    "recorded": time.strftime("%Y-%m-%d"),
                    "commit": _commit(),
                    "interval_ms": INTERVAL_MS,
                    "first_reps": FIRST_REPS,
                    "repeat_reps": REPEAT_REPS,
                    "fast_timeout_ms": FAST_TIMEOUT_MS,
                    "bench": "ESP32 proxy disabled, OLED automation off, "
                    "Home Assistant on the Raspberry Pi's own adapter",
                    "thresholds": "in tools/regression.py, compare()",
                    "devices": results,
                },
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
        print(f"\nbaseline written to {BASELINE}")
        return 0

    print("\nREGRESSED" if failed else "\nno regression")
    return 1 if failed else 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--device", choices=tuple(DEVICES))
    parser.add_argument(
        "--update-baseline",
        action="store_true",
        help="record this run as the baseline instead of judging it",
    )
    args = parser.parse_args()
    if not os.environ.get("HA_TOKEN"):
        raise SystemExit("HA_TOKEN is not set")
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    return asyncio.run(run(args))


if __name__ == "__main__":
    sys.exit(main())
