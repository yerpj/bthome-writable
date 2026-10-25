"""The reference table: what a sealed device costs, for anyone's own case.

Four coefficients, measured once, answer the question an adopter actually has --
*what will this do to my battery* -- for every advertising interval and every
write rate, because the terms add up:

    mean current = floor
                 + advertising, at whatever rate it is running
                 + the fast window after each command
                 + the commands themselves
                 + a rebuild per advertised value that moves, if any

    I(T, n) = floor + (1 - f) * Qadv / T + f * Qadv / Tfast + n * Qcmd / 60
    f = min(1, n * fastTimeout / 60)

`T` is the idle advertising interval in seconds, `n` the commands per minute,
`Qadv` the charge of one advertising event and `Qcmd` the charge of one
command's connection above the idle floor. `f` is the share of the minute spent
in the fast window, which a command opens for `fastTimeout` seconds at
`fastInterval`.

So a 7-by-7 table is four measurements and arithmetic, not 49 recordings:

    python -m tools.power_table --floor 45 --adv-charge 9 --command-charge 100
    python -m tools.power_table --floor 45 --adv-charge 9 --command-charge 100 \\
        --life --capacity-mah 220
    python -m tools.power_table --floor 45 --adv-charge 9 --command-charge 100 \\
        --interval 2000 --writes 3

The third form is one case with its terms broken out, which is what somebody
estimating their own device wants. **Measure the coefficients, publish the
table, and check two of its cells** -- §23 says which two and why: a model
nobody verified is a model nobody should quote.

**The shape of the result matters more than its numbers.** The fast window does
not scale with the write rate the way the commands do: at `fastTimeout` 30 s,
two commands a minute already hold it open permanently, after which the idle
advertising interval cannot be read in the current at all and `fastTimeout` is
the only lever left. Where that crossing falls is what the table shows.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

INTERVALS_MS = (200, 500, 1000, 2000, 3200, 5000, 10000)
"""The module accepts 20 to 10 000 ms; these are the ones worth tabulating."""
RATES = (0, 1, 2, 3, 4, 6)
"""Commands per minute. 0 is the device nobody writes to, which is the floor of
every other row."""


def fit(report: dict) -> dict:
    """The floor and one advertising event, out of a swept sweep's own report.

    The sweep of §23 gives a mean current per advertising interval, and the two
    coefficients are a straight line through them: the current is the floor plus
    one event's charge divided by the interval, so against 1/T it is an
    intercept and a slope. The residual is reported with them, because a model
    that does not fit its own measurement is the first thing to notice.
    """
    xs: list[float] = []
    ys: list[float] = []
    for window in report.get("windows", []):
        label = window.get("label")
        if label is None:
            continue
        interval_s = float(label) / 1000.0
        xs.append(1.0 / interval_s)
        ys.append(float(window["mean_ua"]))
    if len(xs) < 2:
        raise SystemExit(
            "a fit wants at least two labelled windows:"
            " run power_charge with --gaps --labels"
        )
    n = len(xs)
    mean_x = sum(xs) / n
    mean_y = sum(ys) / n
    spread = sum((x - mean_x) ** 2 for x in xs)
    if spread == 0:
        raise SystemExit("every window has the same interval: nothing to fit")
    slope = (
        sum((x - mean_x) * (y - mean_y) for x, y in zip(xs, ys, strict=True)) / spread
    )
    intercept = mean_y - slope * mean_x
    worst = max(abs(y - (intercept + slope * x)) for x, y in zip(xs, ys, strict=True))
    return {
        "floor_ua": round(intercept, 2),
        "adv_charge_uc": round(slope, 3),
        "points": n,
        "worst_residual_ua": round(worst, 2),
    }


class Model:
    """Four measured coefficients, and the arithmetic they support."""

    def __init__(
        self,
        floor_ua: float,
        adv_charge_uc: float,
        command_charge_uc: float,
        fast_interval_ms: float = 100.0,
        fast_timeout_s: float = 30.0,
        rebuild_charge_uc: float = 0.0,
        rebuilds_per_min: float = 0.0,
    ):
        self.floor_ua = floor_ua
        self.adv_charge_uc = adv_charge_uc
        self.command_charge_uc = command_charge_uc
        self.rebuild_charge_uc = rebuild_charge_uc
        self.rebuilds_per_min = rebuilds_per_min
        self.fast_interval_ms = fast_interval_ms
        self.fast_timeout_s = fast_timeout_s

    def fast_share(self, rate_per_min: float) -> float:
        """The share of a minute spent advertising fast, which saturates."""
        return min(1.0, rate_per_min * self.fast_timeout_s / 60.0)

    def terms(self, interval_ms: float, rate_per_min: float) -> dict[str, float]:
        share = self.fast_share(rate_per_min)
        idle = (1.0 - share) * self.adv_charge_uc / (interval_ms / 1000.0)
        fast = share * self.adv_charge_uc / (self.fast_interval_ms / 1000.0)
        commands = rate_per_min * self.command_charge_uc / 60.0
        # A device with an advertised sensor also rebuilds its packet when the
        # value moves, which is the one term the protocol itself does not set.
        rebuilds = self.rebuilds_per_min * self.rebuild_charge_uc / 60.0
        total = self.floor_ua + idle + fast + commands + rebuilds
        return {
            "floor_ua": round(self.floor_ua, 2),
            "advertising_ua": round(idle, 2),
            "fast_window_ua": round(fast, 2),
            "commands_ua": round(commands, 2),
            "rebuilds_ua": round(rebuilds, 2),
            "fast_share": round(share, 3),
            "total_ua": round(total, 2),
        }

    def current_ua(self, interval_ms: float, rate_per_min: float) -> float:
        return self.terms(interval_ms, rate_per_min)["total_ua"]

    def life_days(
        self, interval_ms: float, rate_per_min: float, capacity_mah: float
    ) -> float:
        current = self.current_ua(interval_ms, rate_per_min)
        if current <= 0:
            return 0.0
        return capacity_mah * 1000.0 / current / 24.0

    def saturating_rate(self) -> float:
        """The write rate at which the fast window stops closing.

        Above it the idle advertising interval does not show in the current,
        and `fastTimeout` is the lever instead.
        """
        return 60.0 / self.fast_timeout_s


def table(
    model: Model,
    intervals_ms: tuple[int, ...] = INTERVALS_MS,
    rates: tuple[int, ...] = RATES,
    capacity_mah: float | None = None,
) -> str:
    """The reference table as markdown: microamps, or days on a battery."""
    unit = "days" if capacity_mah else "uA"
    head = (
        "| advertising interval | " + " | ".join(f"{rate}/min" for rate in rates) + " |"
    )
    rule = "|---" * (len(rates) + 1) + "|"
    lines = [
        f"**Mean current in {unit}**"
        if not capacity_mah
        else f"**Days on {capacity_mah:g} mAh**",
        "",
        head,
        rule,
    ]
    for interval in intervals_ms:
        cells = []
        for rate in rates:
            if capacity_mah:
                cells.append(f"{model.life_days(interval, rate, capacity_mah):.0f}")
            else:
                cells.append(f"{model.current_ua(interval, rate):.1f}")
        label = f"{interval} ms" if interval < 1000 else f"{interval / 1000:g} s"
        lines.append(f"| {label} | " + " | ".join(cells) + " |")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--fit",
        type=Path,
        help="a power_charge report from a labelled sweep, from which the floor"
        " and one advertising event's charge are fitted",
    )
    parser.add_argument("--floor", type=float, help="board and firmware idle, uA")
    parser.add_argument(
        "--adv-charge", type=float, help="charge of one advertising event, uC"
    )
    parser.add_argument(
        "--command-charge",
        type=float,
        required=True,
        help="charge of one command's connection above the floor, uC",
    )
    parser.add_argument("--fast-interval", type=float, default=100.0)
    parser.add_argument("--fast-timeout", type=float, default=30.0)
    parser.add_argument(
        "--rebuild-charge",
        type=float,
        default=0.0,
        help="charge of one packet rebuild, uC, for a device that also"
        " advertises a sensor whose value moves",
    )
    parser.add_argument(
        "--rebuilds-per-minute", type=float, default=0.0, help="how often it moves"
    )
    parser.add_argument("--capacity-mah", type=float, default=220.0)
    parser.add_argument(
        "--life", action="store_true", help="also print the table as battery days"
    )
    parser.add_argument("--interval", type=float, help="one case: ms")
    parser.add_argument("--writes", type=float, help="one case: commands per minute")
    parser.add_argument("--out", type=Path, help="write the whole table as JSON")
    args = parser.parse_args(argv)

    floor, adv_charge = args.floor, args.adv_charge
    if args.fit:
        fitted = fit(json.loads(args.fit.read_text(encoding="utf-8")))
        floor = args.floor if args.floor is not None else fitted["floor_ua"]
        adv_charge = (
            args.adv_charge if args.adv_charge is not None else fitted["adv_charge_uc"]
        )
        print(
            f"fitted on {fitted['points']} points: floor {fitted['floor_ua']} uA,"
            f" one advertising event {fitted['adv_charge_uc']} uC,"
            f" worst residual {fitted['worst_residual_ua']} uA"
        )
        print()
    if floor is None or adv_charge is None:
        raise SystemExit("give --floor and --adv-charge, or --fit a sweep report")

    model = Model(
        floor,
        adv_charge,
        args.command_charge,
        args.fast_interval,
        args.fast_timeout,
        args.rebuild_charge,
        args.rebuilds_per_minute,
    )

    if args.interval is not None and args.writes is not None:
        terms = model.terms(args.interval, args.writes)
        print(
            f"{args.interval:g} ms, {args.writes:g} commands a minute:"
            f" {terms['total_ua']} uA"
        )
        print(
            f"  floor {terms['floor_ua']}"
            f" + advertising {terms['advertising_ua']}"
            f" + fast window {terms['fast_window_ua']}"
            f" + commands {terms['commands_ua']}"
            + (f" + rebuilds {terms['rebuilds_ua']}" if terms["rebuilds_ua"] else "")
        )
        print(
            f"  {model.life_days(args.interval, args.writes, args.capacity_mah):.0f}"
            f" days on {args.capacity_mah:g} mAh"
        )
    else:
        print(table(model))
        if args.life:
            print()
            print(table(model, capacity_mah=args.capacity_mah))
        print()
        print(
            f"The fast window stops closing at"
            f" {model.saturating_rate():g} commands a minute,"
            " above which the advertising interval does not show."
        )

    if args.out:
        payload = {
            "coefficients": {
                "floor_ua": floor,
                "adv_charge_uc": adv_charge,
                "command_charge_uc": args.command_charge,
                "fast_interval_ms": args.fast_interval,
                "fast_timeout_s": args.fast_timeout,
                "rebuild_charge_uc": args.rebuild_charge,
                "rebuilds_per_min": args.rebuilds_per_minute,
            },
            "capacity_mah": args.capacity_mah,
            "saturating_rate_per_min": model.saturating_rate(),
            "cells": [
                {
                    "interval_ms": interval,
                    "writes_per_min": rate,
                    **model.terms(interval, rate),
                    "days": round(
                        model.life_days(interval, rate, args.capacity_mah), 1
                    ),
                }
                for interval in INTERVALS_MS
                for rate in RATES
            ],
        }
        args.out.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
        print(f"written to {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
