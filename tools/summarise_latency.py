"""Summarise a write-acknowledgement sweep, in the terms the question was asked in.

    python -m tools.summarise_latency docs/data/write-*.json

Prints, per advertising interval: how long a first command took (median, mean,
spread), how much of it was spent opening the link, and that figure divided by
the interval — the quantity the interval actually governs.

The median leads, because these distributions are not symmetric: a connection
attempt that misses its advertising window waits out another interval, so a few
samples per interval sit far above the rest and pull a mean with them. Where the
mean and the median disagree, the median describes what usually happens and the
difference describes how often it does not.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import statistics
import sys

STALLED_WRITE_MS = 5000
"""A write that took longer than this did not merely take its time: it stalled,
waiting on something that eventually gave up or retried. Counted separately,
because averaging it in describes neither case."""


def phases(row: dict, case: str) -> list[dict]:
    return [s for s in row[case] if not s.get("failed")]


def describe(path: Path) -> None:
    data = json.loads(path.read_text(encoding="utf-8"))
    print(f"\n{data['label']}")
    print(f"  {data.get('measures', '')}")
    print(
        f"\n  {'interval':>9}  {'n':>3}  {'median':>7}  {'mean':>7}  {'spread':>13}"
        f"  {'connect':>8}  {'/interval':>9}  {'following':>9}  {'lost':>4}"
    )

    stalls = 0
    writes = 0
    for row in data["results"]:
        interval = row["interval_ms"]
        first = phases(row, "first")
        following = phases(row, "consecutive")
        lost = sum(1 for s in row["first"] + row["consecutive"] if s.get("failed"))
        stalls += sum(1 for s in first + following if s["write_ms"] > STALLED_WRITE_MS)
        writes += len(first) + len(following)
        if not first:
            print(f"  {interval:>7} ms  {0:>3}  {'all lost':>7}")
            continue

        totals = [s["total_ms"] / 1000 for s in first]
        connect = [s["connect_ms"] / 1000 for s in first]
        follow = [s["total_ms"] / 1000 for s in following]
        print(
            f"  {interval:>7} ms  {len(first):>3}"
            f"  {statistics.median(totals):>6.2f}s"
            f"  {statistics.fmean(totals):>6.2f}s"
            f"  {min(totals):>5.2f}-{max(totals):<6.2f}"
            f"  {statistics.median(connect):>7.2f}s"
            f"  {statistics.median(connect) / (interval / 1000):>8.2f}x"
            f"  {statistics.median(follow) if follow else 0:>8.2f}s"
            f"  {lost:>4}"
        )

    seconds = STALLED_WRITE_MS / 1000
    print(f"\n  writes that stalled past {seconds:.0f} s: {stalls} of {writes}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("data", nargs="+")
    args = parser.parse_args()
    for path in args.data:
        describe(Path(path))
    return 0


if __name__ == "__main__":
    sys.exit(main())
