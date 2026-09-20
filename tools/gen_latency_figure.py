"""Draw the latency sweep: response time against advertising interval.

Reads the JSON `tools.latency_sweep` writes and renders one figure with a curve
per device and per case — the first command after an idle period, and the
commands that follow it. The x axis is logarithmic because the sweep is:
100 ms to 5 s spans most of two decades, and the interesting part is at the top.

    python -m tools.gen_latency_figure docs/data/*.json \
        --out docs/figures/latency-vs-interval.html

The PNG beside it is a screenshot of that file, the same way the other figures
in `docs/figures/` are made.
"""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
import statistics
import sys

W, H = 1080, 660
LEFT, RIGHT, TOP, BOTTOM = 84, 300, 74, 76
PLOT_W = W - LEFT - RIGHT
PLOT_H = H - TOP - BOTTOM

COLOURS = ("#0b5394", "#0b6e4f", "#8a3ffc")
TICKS = (100, 200, 400, 800, 1600, 3200, 5000)


def totals(samples: list[dict]) -> list[float]:
    """Seconds per command that landed, whichever sweep produced it.

    Three shapes, one meaning. The bench-host sweep records its phases in
    seconds (catch the advertising, connect, write); the witness sweep sees only
    the whole thing; the write sweep reads Home Assistant's own timing in
    milliseconds. All add up to one response time.
    """
    out = []
    for s in samples:
        if s.get("failed") or not s.get("fast_window_ok", True):
            continue
        if "total_ms" in s:
            out.append(s["total_ms"] / 1000)
        elif "total" in s:
            out.append(s["total"])
        else:
            out.append(s.get("discover", 0.0) + s["connect"] + s["write"])
    return out


def series(dataset: dict, case: str) -> list[tuple[int, float, float, float]]:
    """(interval, median, min, max) per interval, for one case.

    The median, not the mean: a connection attempt that misses its advertising
    window waits out another interval, so every interval has a few samples far
    above the rest. A mean follows those; the median says what usually happens,
    and the whiskers show how far the rest reach.
    """
    out = []
    for row in dataset["results"]:
        values = totals(row[case])
        if values:
            out.append(
                (
                    row["interval_ms"],
                    statistics.median(values),
                    min(values),
                    max(values),
                )
            )
    return sorted(out)


def x_of(interval: float) -> float:
    lo, hi = math.log10(TICKS[0]), math.log10(TICKS[-1])
    return LEFT + PLOT_W * (math.log10(interval) - lo) / (hi - lo)


def y_of(seconds: float, top: float) -> float:
    return TOP + PLOT_H * (1 - seconds / top)


def svg(datasets: list[dict]) -> str:
    peak = max(
        (
            point[3]
            for data in datasets
            for case in ("first", "consecutive")
            for point in series(data, case)
        ),
        default=1.0,
    )
    top = math.ceil(peak / 5) * 5 or 5
    parts: list[str] = []

    # Horizontal grid and the seconds axis.
    step = 5 if top > 12 else (2 if top > 6 else 1)
    value = 0
    while value <= top:
        y = y_of(value, top)
        parts.append(
            f'<line class="grid" x1="{LEFT}" y1="{y:.1f}"'
            f' x2="{LEFT + PLOT_W}" y2="{y:.1f}"/>'
        )
        parts.append(
            f'<text class="tick y" x="{LEFT - 12}" y="{y + 4:.1f}">{value} s</text>'
        )
        value += step

    for interval in TICKS:
        x = x_of(interval)
        label = f"{interval} ms" if interval < 1000 else f"{interval / 1000:g} s"
        parts.append(
            f'<line class="grid v" x1="{x:.1f}" y1="{TOP}"'
            f' x2="{x:.1f}" y2="{TOP + PLOT_H}"/>'
        )
        parts.append(
            f'<text class="tick x" x="{x:.1f}" y="{TOP + PLOT_H + 24}">{label}</text>'
        )

    legend: list[str] = []
    for index, data in enumerate(datasets):
        colour = COLOURS[index % len(COLOURS)]
        # The idle wait is a property of the run, not of the drawing: a figure
        # that hard-codes it goes stale the first time the sweep is re-run with
        # a different one, and says so in a caption nobody re-reads.
        idle = data.get("idle_wait_s")
        after = f"after {idle:.0f} s idle" if idle else "after a quiet period"
        for case, dash, name in (
            ("first", "", f"first command {after}"),
            ("consecutive", "6 4", "commands that follow"),
        ):
            points = series(data, case)
            if not points:
                continue
            path = " ".join(
                f"{'M' if i == 0 else 'L'}{x_of(p[0]):.1f} {y_of(p[1], top):.1f}"
                for i, p in enumerate(points)
            )
            parts.append(
                f'<path d="{path}" fill="none" stroke="{colour}" stroke-width="2.4"'
                f' stroke-dasharray="{dash}" stroke-linejoin="round"/>'
            )
            for interval, mean, low, high in points:
                x = x_of(interval)
                parts.append(
                    f'<line x1="{x:.1f}" y1="{y_of(low, top):.1f}" x2="{x:.1f}"'
                    f' y2="{y_of(high, top):.1f}" stroke="{colour}" stroke-width="1"'
                    f' opacity="0.45"/>'
                )
                parts.append(
                    f'<circle cx="{x:.1f}" cy="{y_of(mean, top):.1f}" r="3.4"'
                    f' fill="{"#fff" if case == "consecutive" else colour}"'
                    f' stroke="{colour}" stroke-width="2"/>'
                )
            legend.append(
                f'<div class="key"><span class="swatch" style="--c:{colour};'
                f'{"--d:dashed" if case == "consecutive" else "--d:solid"}"></span>'
                f'<b>{data["label"]}</b><br><span class="muted">{name}</span></div>'
            )

    parts.append(
        f'<line class="axis" x1="{LEFT}" y1="{TOP + PLOT_H}" x2="{LEFT + PLOT_W}"'
        f' y2="{TOP + PLOT_H}"/>'
    )
    parts.append(
        f'<line class="axis" x1="{LEFT}" y1="{TOP}" x2="{LEFT}" y2="{TOP + PLOT_H}"/>'
    )
    parts.append(
        f'<text class="axis-label" x="{LEFT + PLOT_W / 2:.0f}" y="{H - 22}">'
        "advertising interval (logarithmic)</text>"
    )
    return "\n".join(parts), "\n".join(legend)


def render(datasets: list[dict]) -> str:
    body, legend = svg(datasets)
    return f"""<!doctype html>
<meta charset="utf-8">
<style>
  body {{
    margin: 0; background: #fff; color: #1a1d21; width: {W}px;
    font: 15px/1.5 -apple-system, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
  }}
  h1 {{ font-size: 21px; margin: 26px 40px 3px; letter-spacing: -0.01em; }}
  .sub {{ color: #5b6570; font-size: 14px; margin: 0 40px 0; }}
  svg {{ display: block; }}
  .grid {{ stroke: #e6eaee; stroke-width: 1; }}
  .grid.v {{ stroke-dasharray: 3 5; }}
  .axis {{ stroke: #9aa5b1; stroke-width: 1.2; }}
  .tick {{ fill: #5b6570; font-size: 12px; }}
  .tick.y {{ text-anchor: end; }}
  .tick.x {{ text-anchor: middle; }}
  .axis-label {{ fill: #5b6570; font-size: 12.5px; text-anchor: middle; }}
  .legend {{
    position: absolute; left: {LEFT + PLOT_W + 34}px;
    top: {TOP + 6}px; width: {RIGHT - 60}px;
  }}
  .key {{ margin-bottom: 14px; font-size: 12.5px; line-height: 1.45; }}
  .key b {{ font-weight: 600; }}
  .muted {{ color: #5b6570; }}
  .swatch {{
    display: inline-block; width: 26px; height: 0; vertical-align: middle;
    border-top: 2.6px var(--d) var(--c); margin-right: 8px;
  }}
</style>
<h1>Response time against advertising interval</h1>
<p class="sub">From the command reaching Home Assistant to the device acknowledging the
GATT write. Median of ten commands issued after a quiet period, and of eight issued
straight afterwards; whiskers span every sample.</p>
<div style="position:relative">
<svg width="{W}" height="{H}" viewBox="0 0 {W} {H}">
{body}
</svg>
<div class="legend">
{legend}
</div>
</div>
"""


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("data", nargs="+", help="JSON files from tools.latency_sweep")
    parser.add_argument("--out", required=True)
    args = parser.parse_args()

    datasets = [json.loads(Path(p).read_text(encoding="utf-8")) for p in args.data]
    out = Path(args.out)
    out.write_text(render(datasets), encoding="utf-8", newline="\n")
    print(f"wrote {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
