"""Turn a power-meter CSV into the figures §23 asks for.

A current trace answers two different questions and they need different
arithmetic. *What does this device cost to leave alone* is a mean current over
minutes, and it ends in a battery life. *What does one command cost* is a charge
over a window of seconds, and a mean current there means nothing: the honest
number is microcoulombs, which is what divides into a battery and what scales
with a command rate.

This reads an exported trace -- a Nordic PPK2 export is the one it was written
for -- and reports both:

    python -m tools.power_charge trace.csv
    python -m tools.power_charge trace.csv --digital D0 --baseline auto
    python -m tools.power_charge trace.csv --window 4200-7300 --out out.json

Windows come from a digital channel when the board under the meter drives one
(`espruino/bench/power-arms.js` raises its marker pin for exactly the
connection a command runs in), and from `--window` when it does not.

**`--baseline auto` is usually what you want for a window.** It takes the
median current of everything outside the windows and reports each window's
charge above it, which is the cost of the command rather than the cost of the
command plus the advertising that would have happened anyway.

Column names are matched loosely, because exports differ between versions of
the Power Profiler: a timestamp column, a current column whose unit is read
from its header, and digital channels named `D0` or `Logic 0`. A digital
channel that exports as `X` rather than 0 or 1 is a known PPK2 export fault --
those samples hold their previous value here, and the count is reported so a
trace with many of them is not mistaken for a clean one.
"""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path
import re
import statistics as st
import sys

CR2032_MAH = 220.0
"""A coin cell's nominal capacity, which is what a Puck.js runs on. It is
nominal in the way datasheets are: a real cell delivers less of it the colder
and the pulsier the load, so a life computed from it is an upper bound."""

TIME_NAMES = ("timestamp", "time")
CURRENT_NAMES = ("current", "amps")
"""Not "amp": a column called `Timestamp(ms)` contains it."""
UNITS = {"ua": 1.0, "µa": 1.0, "ma": 1000.0, "a": 1e6, "na": 0.001}
DIGITAL = re.compile(r"^\s*(?:d|logic\s*)(\d)\s*(?:\(.*\))?\s*$", re.IGNORECASE)


def _unit_scale(header: str) -> float:
    """How many microamps one unit of this column is, from its own header."""
    inside = re.search(r"[(\[]\s*([a-zµ]+)\s*[)\]]", header, re.IGNORECASE)
    if inside is None:
        return 1.0
    return UNITS.get(inside.group(1).lower(), 1.0)


def _column(headers: list[str], names: tuple[str, ...], skip: int = -1) -> int:
    for index, header in enumerate(headers):
        if index == skip:
            continue
        lowered = header.strip().lower()
        if any(name in lowered for name in names):
            return index
    raise SystemExit(f"no column among {headers} looks like {names[0]}")


class Trace:
    """Samples of one current trace, in milliseconds and microamps."""

    def __init__(self, times: list[float], currents: list[float], digital: dict):
        self.times = times
        self.currents = currents
        self.digital = digital
        self.unknown = 0

    @classmethod
    def read(cls, path: Path, unit: str | None = None) -> Trace:
        with path.open(newline="", encoding="utf-8-sig") as handle:
            rows = csv.reader(handle)
            headers = next(rows, None)
            if headers is None:
                raise SystemExit(f"{path}: empty")
            time_at = _column(headers, TIME_NAMES)
            current_at = _column(headers, CURRENT_NAMES, skip=time_at)
            scale = UNITS[unit.lower()] if unit else _unit_scale(headers[current_at])
            channels = {
                f"D{found.group(1)}": index
                for index, header in enumerate(headers)
                if (found := DIGITAL.match(header))
            }

            times: list[float] = []
            currents: list[float] = []
            digital: dict[str, list[int]] = {name: [] for name in channels}
            unknown = 0
            for row in rows:
                if not row or len(row) <= max(time_at, current_at):
                    continue
                try:
                    time_ms = float(row[time_at])
                    current_ua = float(row[current_at]) * scale
                except ValueError:
                    continue
                times.append(time_ms)
                currents.append(current_ua)
                for name, index in channels.items():
                    raw = row[index].strip() if index < len(row) else ""
                    if raw in ("0", "1"):
                        digital[name].append(int(raw))
                    else:
                        unknown += 1
                        digital[name].append(digital[name][-1] if digital[name] else 0)

        if not times:
            raise SystemExit(f"{path}: no samples")
        trace = cls(times, currents, digital)
        trace.unknown = unknown
        return trace

    @property
    def period_ms(self) -> float:
        """The sampling period, from the samples rather than from a setting."""
        if len(self.times) < 2:
            return 0.0
        return (self.times[-1] - self.times[0]) / (len(self.times) - 1)

    def charge_uc(self, first: int, last: int) -> float:
        """Microcoulombs between two sample indices, rectangle by rectangle."""
        return sum(self.currents[first:last]) * self.period_ms / 1000.0

    def windows(self, channel: str) -> list[tuple[int, int]]:
        """Index pairs for every stretch where a digital channel is high."""
        levels = self.digital.get(channel)
        if levels is None:
            raise SystemExit(
                f"no channel {channel} in this export"
                f" (found {sorted(self.digital) or 'none'})"
            )
        found: list[tuple[int, int]] = []
        start = None
        for index, level in enumerate(levels):
            if level and start is None:
                start = index
            elif not level and start is not None:
                found.append((start, index))
                start = None
        if start is not None:
            found.append((start, len(levels)))
        return found

    def at_times(self, first_ms: float, last_ms: float) -> tuple[int, int]:
        first = next(
            (i for i, t in enumerate(self.times) if t >= first_ms), len(self.times)
        )
        last = next(
            (i for i, t in enumerate(self.times) if t > last_ms), len(self.times)
        )
        return first, last


def _life(mean_ua: float, capacity_mah: float) -> dict:
    if mean_ua <= 0:
        return {}
    hours = capacity_mah * 1000.0 / mean_ua
    return {
        "hours": round(hours, 1),
        "days": round(hours / 24.0, 1),
        "years": round(hours / 24.0 / 365.0, 2),
    }


def summarise(
    trace: Trace,
    windows: list[tuple[int, int]],
    baseline_ua: float | None,
    capacity_mah: float,
) -> dict:
    span_ms = trace.times[-1] - trace.times[0] + trace.period_ms
    inside = {index for first, last in windows for index in range(first, last)}
    outside = [c for i, c in enumerate(trace.currents) if i not in inside]

    if baseline_ua is None and outside:
        floor = st.median(outside)
    else:
        floor = baseline_ua or 0.0

    whole_mean = st.mean(trace.currents)
    report: dict = {
        "samples": len(trace.currents),
        "period_ms": round(trace.period_ms, 6),
        "span_s": round(span_ms / 1000.0, 3),
        "mean_ua": round(whole_mean, 2),
        "median_ua": round(st.median(trace.currents), 2),
        "max_ua": round(max(trace.currents), 1),
        "charge_uc": round(trace.charge_uc(0, len(trace.currents)), 1),
        "life_at_this_mean": _life(whole_mean, capacity_mah),
        "capacity_mah": capacity_mah,
        "unknown_digital_samples": trace.unknown,
    }
    if outside and len(outside) != len(trace.currents):
        report["outside_windows_median_ua"] = round(st.median(outside), 2)

    if not windows:
        return report

    each = []
    for first, last in windows:
        charge = trace.charge_uc(first, last)
        duration = (last - first) * trace.period_ms
        each.append(
            {
                "start_ms": round(trace.times[first], 3),
                "duration_ms": round(duration, 2),
                "mean_ua": round(st.mean(trace.currents[first:last]), 2),
                "max_ua": round(max(trace.currents[first:last]), 1),
                "charge_uc": round(charge, 2),
                "excess_uc": round(charge - floor * duration / 1000.0, 2),
            }
        )

    def medians(field: str) -> float:
        return round(st.median([w[field] for w in each]), 2)

    report["windows"] = each
    report["window_summary"] = {
        "n": len(each),
        "baseline_ua": round(floor, 2),
        "median_duration_ms": medians("duration_ms"),
        "median_mean_ua": medians("mean_ua"),
        "median_charge_uc": medians("charge_uc"),
        "median_excess_uc": medians("excess_uc"),
        "total_excess_uc": round(sum(w["excess_uc"] for w in each), 2),
    }
    return report


def _print(report: dict) -> None:
    print(
        f"{report['samples']} samples, {report['span_s']} s"
        f" at {report['period_ms'] * 1000:.0f} us"
    )
    print(
        f"  whole trace: mean {report['mean_ua']} uA,"
        f" median {report['median_ua']}, peak {report['max_ua']},"
        f" charge {report['charge_uc']} uC"
    )
    life = report.get("life_at_this_mean") or {}
    if life:
        print(
            f"  at that mean, {report['capacity_mah']} mAh lasts"
            f" {life['days']} days ({life['years']} years)"
        )
    if report.get("unknown_digital_samples"):
        print(
            f"  WARNING: {report['unknown_digital_samples']} digital samples were"
            " neither 0 nor 1 and held their previous value"
        )
    summary = report.get("window_summary")
    if not summary:
        return
    print(
        f"  {summary['n']} window{'' if summary['n'] == 1 else 's'},"
        f" baseline {summary['baseline_ua']} uA:"
        f" median {summary['median_duration_ms']} ms,"
        f" {summary['median_mean_ua']} uA,"
        f" {summary['median_charge_uc']} uC"
        f" ({summary['median_excess_uc']} uC above the baseline)"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("csv", type=Path, help="an exported current trace")
    parser.add_argument(
        "--digital", help="a digital channel whose high stretches are the windows"
    )
    parser.add_argument(
        "--window",
        action="append",
        default=[],
        metavar="FIRST-LAST",
        help="a window in milliseconds, repeatable",
    )
    parser.add_argument(
        "--baseline",
        default="auto",
        help='microamps to count as the floor, or "auto" for the median outside'
        " the windows",
    )
    parser.add_argument(
        "--unit", help="override the current column's unit (uA, mA, A, nA)"
    )
    parser.add_argument(
        "--capacity-mah",
        type=float,
        default=CR2032_MAH,
        help=f"battery capacity for the life figure (default {CR2032_MAH})",
    )
    parser.add_argument("--out", type=Path, help="write the report as JSON")
    parser.add_argument("--label", help="what this trace is, carried into the JSON")
    args = parser.parse_args(argv)

    trace = Trace.read(args.csv, args.unit)

    windows: list[tuple[int, int]] = []
    if args.digital:
        windows += trace.windows(args.digital)
    for span in args.window:
        try:
            first_ms, last_ms = (float(part) for part in span.split("-", 1))
        except ValueError:
            raise SystemExit(f"--window wants FIRST-LAST in ms, not {span!r}") from None
        windows.append(trace.at_times(first_ms, last_ms))

    baseline = None if args.baseline == "auto" else float(args.baseline)
    report = summarise(trace, windows, baseline, args.capacity_mah)
    report["source"] = args.csv.name
    if args.label:
        report["label"] = args.label
    _print(report)

    if args.out:
        args.out.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
        print(f"  written to {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
