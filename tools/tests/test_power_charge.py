"""The charge arithmetic of §23, tested without a meter.

A power figure nobody can check is a power figure nobody will believe, so the
part that turns samples into microcoulombs is exercised against traces whose
answer is known by hand. The synthetic traces below are shaped like the real
arms: a flat advertising floor with a burst in it, marked by a digital channel
the way `espruino/bench/power-arms.js` marks a connection.
"""

from __future__ import annotations

from pathlib import Path

from tools.power_charge import Trace, summarise

PERIOD_MS = 1.0


def write(path: Path, rows: list[tuple[float, float, int]], header: str) -> Path:
    lines = [header] + [f"{t},{c},{d}" for t, c, d in rows]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def flat_with_burst(
    floor_ua: float = 10.0, burst_ua: float = 1010.0
) -> list[tuple[float, float, int]]:
    """A hundred samples at the floor, ten of burst with the marker high, a
    hundred back at the floor: 110 ms of floor and 10 ms of burst."""
    rows = [(float(i), floor_ua, 0) for i in range(100)]
    rows += [(float(100 + i), burst_ua, 1) for i in range(10)]
    rows += [(float(110 + i), floor_ua, 0) for i in range(100)]
    return rows


def test_one_marked_window_is_found_and_integrated(tmp_path: Path) -> None:
    path = write(tmp_path / "t.csv", flat_with_burst(), "Timestamp(ms),Current(uA),D0")
    trace = Trace.read(path)
    assert trace.period_ms == PERIOD_MS

    report = summarise(trace, trace.windows("D0"), None, 220.0)
    summary = report["window_summary"]
    assert summary["n"] == 1
    assert summary["median_duration_ms"] == 10.0
    # 1010 uA for 10 ms is 10.1 uC, of which the floor would have cost 0.1.
    assert summary["median_charge_uc"] == 10.1
    assert summary["median_excess_uc"] == 10.0
    assert summary["baseline_ua"] == 10.0


def test_the_baseline_can_be_given_rather_than_inferred(tmp_path: Path) -> None:
    path = write(tmp_path / "t.csv", flat_with_burst(), "Timestamp(ms),Current(uA),D0")
    trace = Trace.read(path)
    report = summarise(trace, trace.windows("D0"), 0.0, 220.0)
    assert report["window_summary"]["median_excess_uc"] == 10.1


def test_a_battery_life_comes_out_of_the_mean(tmp_path: Path) -> None:
    rows = [(float(i), 10.0, 0) for i in range(1000)]
    path = write(tmp_path / "t.csv", rows, "Timestamp(ms),Current(uA),D0")
    report = summarise(Trace.read(path), [], None, 220.0)
    assert report["mean_ua"] == 10.0
    # 220 mAh at 10 uA is 22 000 hours, which is two and a half years.
    assert report["life_at_this_mean"]["hours"] == 22000.0
    assert report["life_at_this_mean"]["years"] == 2.51


def test_two_windows_are_summarised_by_their_median(tmp_path: Path) -> None:
    rows = [(float(i), 10.0, 0) for i in range(50)]
    rows += [(float(50 + i), 1010.0, 1) for i in range(10)]
    rows += [(float(60 + i), 10.0, 0) for i in range(50)]
    rows += [(float(110 + i), 2010.0, 1) for i in range(10)]
    rows += [(float(120 + i), 10.0, 0) for i in range(50)]
    path = write(tmp_path / "t.csv", rows, "Timestamp(ms),Current(uA),D0")
    trace = Trace.read(path)
    report = summarise(trace, trace.windows("D0"), None, 220.0)
    assert report["window_summary"]["n"] == 2
    assert report["window_summary"]["median_charge_uc"] == 15.1
    assert report["window_summary"]["total_excess_uc"] == 30.0


def test_a_milliamp_column_is_scaled_from_its_own_header(tmp_path: Path) -> None:
    rows = [(float(i), 0.010, 0) for i in range(100)]
    path = write(tmp_path / "t.csv", rows, "Timestamp(ms),Current(mA),D0")
    assert summarise(Trace.read(path), [], None, 220.0)["mean_ua"] == 10.0


def test_channels_named_the_other_way_are_still_found(tmp_path: Path) -> None:
    path = write(tmp_path / "t.csv", flat_with_burst(), "Time(ms),Current(uA),Logic 0")
    trace = Trace.read(path)
    assert sorted(trace.digital) == ["D0"]
    assert len(trace.windows("D0")) == 1


def test_an_unknown_digital_sample_holds_and_is_counted(tmp_path: Path) -> None:
    """The PPK2 export is known to emit `X` for a digital channel. A trace with
    many of them is not a trace to publish from, so the count is reported."""
    lines = ["Timestamp(ms),Current(uA),D0", "0,10,0", "1,1010,X", "2,10,0"]
    path = tmp_path / "t.csv"
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    trace = Trace.read(path)
    assert trace.unknown == 1
    assert trace.digital["D0"] == [0, 0, 0]
    assert summarise(trace, [], None, 220.0)["unknown_digital_samples"] == 1


def test_a_window_can_be_cut_by_time_instead(tmp_path: Path) -> None:
    path = write(tmp_path / "t.csv", flat_with_burst(), "Timestamp(ms),Current(uA),D0")
    trace = Trace.read(path)
    assert trace.at_times(100.0, 109.0) == trace.windows("D0")[0]
