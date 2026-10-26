"""Turn a power-meter CSV into the figures §23 asks for.

A current trace answers two different questions and they need different
arithmetic. *What does this device cost to leave alone* is a mean current over
minutes, and it ends in a battery life. *What does one command cost* is a charge
over a window of seconds, and a mean current there means nothing: the honest
number is microcoulombs, which is what divides into a battery and what scales
with a command rate.

This reads an exported trace and reports both:

    python -m tools.power_charge trace.csv
    python -m tools.power_charge trace.csv --digital GPI1 --baseline auto
    python -m tools.power_charge trace.csv --digital GPI1 --digital-csv gpi.csv
    python -m tools.power_charge trace.csv --window 4200-7300 --out out.json

**It reads the file it is given rather than a format it was promised.** The
measurement of §23 is made on an Otii Arc Pro and the arithmetic has to survive
the export being a column of seconds and amperes, or milliseconds and microamps
as a Nordic PPK2 writes them, or the marker channel arriving in a file of its own
(`--digital-csv`, aligned by timestamp rather than by row). Units come from each
column's own header; `--time-unit` and `--unit` are there for an export whose
header does not say.

Windows come from a digital channel when the board under the meter drives one
(`espruino/bench/power-arms.js` raises its marker pin for exactly the
connection a command runs in), and from `--window` when it does not.

**`--baseline auto` is usually what you want for a window.** It takes the
median current of everything outside the windows and reports each window's
charge above it, which is the cost of the command rather than the cost of the
command plus the advertising that would have happened anyway.

**A marker channel may export as a voltage rather than as a bit**, which is
why high is a threshold (`--digital-threshold`, 0.5 by default) and not an
equality.

Column names are matched loosely, because every instrument names them its own
way: a timestamp column, a current column whose unit is read from its header,
and digital channels named `GPI1`, `D0` or `Logic 0`. A digital sample that is
neither a number nor a bit -- the PPK2 is known to export `X` -- holds its
previous value, and the count is reported so a trace full of them is not
mistaken for a clean one.

**One warning is worth heeding: a window of a handful of samples.** An Arc Pro
samples current at up to 4 ksps, so 250 us a sample: a connection or a rebuild
is hundreds of samples and integrates honestly, while a single advertising event
is six and its peak is not a figure this rig produces. Windows thinner than ten
samples are counted and reported as such.
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
TIME_UNITS = {"s": 1000.0, "sec": 1000.0, "ms": 1.0, "us": 0.001, "µs": 0.001}
DIGITAL = re.compile(r"^\s*(?:gpi\s*|d|logic\s*)(\d)\s*(?:[(\[].*)?$", re.IGNORECASE)
THIN_WINDOW = 10
"""Fewer samples than this in a window and the charge is a guess, not a
measurement: at an Arc Pro's 250 us a sample that is 2.5 ms."""


def _header_unit(header: str) -> str | None:
    inside = re.search(r"[(\[]\s*([a-zµ]+)\s*[)\]]", header, re.IGNORECASE)
    return inside.group(1).lower() if inside else None


def _channel_name(header: str) -> str:
    """A marker channel under the name its own instrument gives it.

    `GPI1` on an Otii, `D0` on a PPK2, and `Logic 0` which is the same D0 under
    another export's spelling.
    """
    bare = re.split(r"[(\[]", header)[0].strip()
    squashed = re.sub(r"\s+", "", bare).upper()
    if squashed.startswith("LOGIC"):
        return "D" + squashed[len("LOGIC") :]
    return squashed


def _unit_scale(header: str) -> float:
    """How many microamps one unit of this column is, from its own header."""
    return UNITS.get(_header_unit(header) or "", 1.0)


def _time_scale(header: str, override: str | None) -> float:
    """How many milliseconds one unit of the time column is."""
    if override:
        return TIME_UNITS[override.lower().lstrip("(").rstrip(")")]
    found = TIME_UNITS.get(_header_unit(header) or "")
    if found is None:
        raise SystemExit(
            f"the time column {header!r} does not say its unit:"
            " pass --time-unit s, ms or us"
        )
    return found


def _column(
    headers: list[str], names: tuple[str, ...], skip: int = -1, required: bool = True
) -> int:
    for index, header in enumerate(headers):
        if index == skip:
            continue
        lowered = header.strip().lower()
        if any(name in lowered for name in names):
            return index
    if not required:
        return -1
    raise SystemExit(f"no column among {headers} looks like {names[0]}")


class Trace:
    """Samples of one current trace, in milliseconds and microamps."""

    def __init__(self, times: list[float], currents: list[float], digital: dict):
        self.times = times
        self.currents = currents
        self.digital = digital
        self.unknown = 0

    @classmethod
    def read(
        cls,
        path: Path,
        unit: str | None = None,
        time_unit: str | None = None,
        require_current: bool = True,
    ) -> Trace:
        """One exported file, normalised to milliseconds and microamps.

        `require_current` is false for a companion file holding nothing but a
        marker channel, which some instruments export on its own.
        """
        with path.open(newline="", encoding="utf-8-sig") as handle:
            rows = csv.reader(handle)
            headers = next(rows, None)
            if headers is None:
                raise SystemExit(f"{path}: empty")
            time_at = _column(headers, TIME_NAMES)
            time_scale = _time_scale(headers[time_at], time_unit)
            current_at = _column(
                headers, CURRENT_NAMES, skip=time_at, required=require_current
            )
            scale = (
                1.0
                if current_at < 0
                else UNITS[unit.lower()]
                if unit
                else _unit_scale(headers[current_at])
            )
            channels = {
                _channel_name(header): index
                for index, header in enumerate(headers)
                if DIGITAL.match(header)
            }

            times: list[float] = []
            currents: list[float] = []
            digital: dict[str, list[float]] = {name: [] for name in channels}
            unknown = 0
            for row in rows:
                if not row or len(row) <= max(time_at, current_at):
                    continue
                try:
                    time_ms = float(row[time_at]) * time_scale
                    current_ua = (
                        0.0 if current_at < 0 else float(row[current_at]) * scale
                    )
                except ValueError:
                    continue
                times.append(time_ms)
                currents.append(current_ua)
                for name, index in channels.items():
                    raw = row[index].strip() if index < len(row) else ""
                    try:
                        digital[name].append(float(raw))
                    except ValueError:
                        unknown += 1
                        digital[name].append(
                            digital[name][-1] if digital[name] else 0.0
                        )

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

    def high_spans_ms(
        self, channel: str, threshold: float = 0.5
    ) -> list[tuple[float, float]]:
        """When a marker channel was high, in milliseconds.

        In milliseconds rather than in row numbers, because the channel may
        have come from another file at another sample rate.
        """
        levels = self.digital.get(_channel_name(channel))
        if levels is None:
            raise SystemExit(
                f"no channel {channel} in this export"
                f" (found {sorted(self.digital) or 'none'})"
            )
        found: list[tuple[float, float]] = []
        start: float | None = None
        for index, level in enumerate(levels):
            if level >= threshold and start is None:
                start = self.times[index]
            elif level < threshold and start is not None:
                found.append((start, self.times[index]))
                start = None
        if start is not None:
            found.append((start, self.times[-1] + self.period_ms))
        return found

    def low_spans_ms(
        self, channel: str, threshold: float = 0.5
    ) -> list[tuple[float, float]]:
        """The quiet between marker pulses, which is where a sweep's steps are.

        A device walking a list of advertising intervals pulses the marker at
        each step, so the stretch that belongs to a step is the one *between*
        two pulses rather than under one.
        """
        spans: list[tuple[float, float]] = []
        cursor = self.times[0]
        for first, end in self.high_spans_ms(channel, threshold):
            if first > cursor:
                spans.append((cursor, first))
            cursor = end
        last = self.times[-1] + self.period_ms
        if cursor < last:
            spans.append((cursor, last))
        return spans

    def windows(
        self,
        channel: str,
        threshold: float = 0.5,
        marker: Trace | None = None,
        gaps: bool = False,
    ) -> list[tuple[int, int]]:
        """Index pairs into this trace for every stretch the marker was high.

        `marker` is another trace whose channel is used instead of this one's,
        which is how a marker exported to its own file is applied here.
        """
        source = marker or self
        spans = (
            source.low_spans_ms(channel, threshold)
            if gaps
            else source.high_spans_ms(channel, threshold)
        )
        return [self.at_times(first, last) for first, last in spans]

    def at_times(self, first_ms: float, end_ms: float) -> tuple[int, int]:
        """Sample indices for a span of time, the end exclusive.

        A marker sample stands for the time until the next one, so a span runs
        from the first high sample to the first low one and not to the last
        high one -- which is the difference between a window of ten samples and
        a window of one when the marker was exported at a tenth of the rate.
        """
        first = next(
            (i for i, t in enumerate(self.times) if t >= first_ms), len(self.times)
        )
        last = next(
            (i for i, t in enumerate(self.times) if t >= end_ms), len(self.times)
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
        "thin_windows": sum(1 for first, last in windows if last - first < THIN_WINDOW),
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
    if report.get("thin_windows"):
        print(
            f"  WARNING: {report['thin_windows']} of the windows hold fewer than"
            f" {THIN_WINDOW} samples, which is a guess rather than a charge"
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
        help="a window in milliseconds, end exclusive, repeatable",
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
        "--time-unit", help="override the time column's unit (s, ms, us)"
    )
    parser.add_argument(
        "--digital-csv",
        type=Path,
        help="a second export holding the marker channel, aligned by timestamp",
    )
    parser.add_argument(
        "--gaps",
        action="store_true",
        help="measure the stretches *between* marker pulses rather than under"
        " them, which is how a device-driven sweep marks its steps",
    )
    parser.add_argument(
        "--labels",
        help="comma-separated names for the windows, in order, e.g. the swept"
        " advertising intervals. With --gaps there is one window more than there"
        " are steps, because the stretch before the first marker pulse is a gap"
        " too: label it - and the fit will skip it",
    )
    parser.add_argument(
        "--digital-threshold",
        type=float,
        default=0.5,
        help="above this the marker counts as high, for a channel exported as a"
        " voltage (default 0.5)",
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

    trace = Trace.read(args.csv, args.unit, args.time_unit)
    marker = (
        Trace.read(args.digital_csv, args.unit, args.time_unit, require_current=False)
        if args.digital_csv
        else None
    )
    if marker and not args.digital:
        raise SystemExit("--digital-csv needs --digital to say which channel")

    windows: list[tuple[int, int]] = []
    if args.digital:
        windows += trace.windows(
            args.digital, args.digital_threshold, marker, args.gaps
        )
    for span in args.window:
        try:
            first_ms, last_ms = (float(part) for part in span.split("-", 1))
        except ValueError:
            raise SystemExit(f"--window wants FIRST-LAST in ms, not {span!r}") from None
        windows.append(trace.at_times(first_ms, last_ms))

    # Outside a sweep's steps there is nothing but the marker pulses, so an
    # inferred floor would be the pulse rather than the device.
    if args.baseline == "auto" and args.gaps:
        baseline: float | None = 0.0
    elif args.baseline == "auto":
        baseline = None
    else:
        baseline = float(args.baseline)
    report = summarise(trace, windows, baseline, args.capacity_mah)
    labels = [name.strip() for name in args.labels.split(",")] if args.labels else []
    for index, window in enumerate(report.get("windows", [])):
        if index < len(labels):
            window["label"] = labels[index]
    if labels and len(labels) != len(report.get("windows", [])):
        print(
            f"  WARNING: {len(labels)} labels for"
            f" {len(report.get('windows', []))} windows"
        )

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
