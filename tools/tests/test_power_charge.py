"""The charge arithmetic of §23, tested without a meter.

A power figure nobody can check is a power figure nobody will believe, so the
part that turns samples into microcoulombs is exercised against traces whose
answer is known by hand. The synthetic traces below are shaped like the real
arms: a flat advertising floor with a burst in it, marked by a digital channel
the way `espruino/bench/power-arms.js` marks a connection.
"""

from __future__ import annotations

import json
from pathlib import Path
import statistics as st

import pytest

from tools.power_charge import Trace, main, summarise

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
    assert trace.at_times(100.0, 110.0) == trace.windows("D0")[0]


def test_an_otii_shaped_export_is_read_in_seconds_and_amps(tmp_path: Path) -> None:
    """Seconds and amperes with the marker on GPI1, which is the shape the
    measurement of §23 is actually made in."""
    rows = [(i / 1000.0, 10e-6, 0) for i in range(100)]
    rows += [((100 + i) / 1000.0, 1010e-6, 1) for i in range(10)]
    rows += [((110 + i) / 1000.0, 10e-6, 0) for i in range(100)]
    lines = ["Timestamp(s),Current(A),GPI1"] + [f"{t},{c},{d}" for t, c, d in rows]
    path = tmp_path / "otii.csv"
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    trace = Trace.read(path)
    assert sorted(trace.digital) == ["GPI1"]
    assert trace.period_ms == 1.0
    report = summarise(trace, trace.windows("GPI1"), None, 220.0)
    assert report["window_summary"]["median_charge_uc"] == 10.1
    assert report["mean_ua"] == 57.62


def test_a_time_column_without_a_unit_asks_for_one(tmp_path: Path) -> None:
    path = tmp_path / "bare.csv"
    path.write_text("Timestamp,Current(A)\n0,1e-5\n0.001,1e-5\n", encoding="utf-8")
    with pytest.raises(SystemExit, match="--time-unit"):
        Trace.read(path)
    assert Trace.read(path, time_unit="s").period_ms == 1.0


def test_a_marker_in_its_own_file_is_aligned_by_timestamp(tmp_path: Path) -> None:
    """A separate marker file, sampled ten times slower than the current, still
    cuts the window where the marker says and not where its rows fall."""
    current = ["Timestamp(s),Current(A)"]
    current += [
        f"{i / 1000.0},{1010e-6 if 100 <= i < 110 else 10e-6}" for i in range(210)
    ]
    (tmp_path / "c.csv").write_text("\n".join(current) + "\n", encoding="utf-8")

    marker = ["Timestamp(s),GPI1"]
    marker += [f"{i / 100.0},{1 if 10 <= i < 11 else 0}" for i in range(21)]
    (tmp_path / "m.csv").write_text("\n".join(marker) + "\n", encoding="utf-8")

    trace = Trace.read(tmp_path / "c.csv")
    side = Trace.read(tmp_path / "m.csv", require_current=False)
    windows = trace.windows("GPI1", marker=side)
    assert windows == [(100, 110)]
    assert (
        summarise(trace, windows, None, 220.0)["window_summary"]["median_charge_uc"]
        == 10.1
    )


def test_a_marker_exported_as_a_voltage_is_still_a_marker(tmp_path: Path) -> None:
    rows = [(float(i), 10.0, 0.02) for i in range(100)]
    rows += [(float(100 + i), 1010.0, 3.28) for i in range(10)]
    rows += [(float(110 + i), 10.0, 0.02) for i in range(100)]
    path = write(tmp_path / "v.csv", rows, "Timestamp(ms),Current(uA),GPI1(V)")
    trace = Trace.read(path)
    assert trace.windows("GPI1", threshold=1.5) == [(100, 110)]


def test_a_window_of_a_handful_of_samples_is_flagged(tmp_path: Path) -> None:
    """At an Arc Pro's 250 us a sample, one advertising event is six samples:
    a charge computed from it is a guess, and the report has to say so."""
    rows = [(i * 0.25, 10.0, 0) for i in range(100)]
    rows += [((100 + i) * 0.25, 6000.0, 1) for i in range(6)]
    rows += [((106 + i) * 0.25, 10.0, 0) for i in range(100)]
    path = write(tmp_path / "thin.csv", rows, "Timestamp(ms),Current(uA),GPI1")
    trace = Trace.read(path)
    report = summarise(trace, trace.windows("GPI1"), None, 220.0)
    assert report["thin_windows"] == 1


def test_the_steps_of_a_sweep_are_the_quiet_between_its_pulses(tmp_path: Path) -> None:
    """A device walking advertising intervals pulses the marker at each step, so
    what belongs to a step is the stretch between two pulses."""
    rows: list[tuple[float, float, int]] = []
    for step, current in enumerate((90.0, 50.0, 20.0)):
        start = step * 100
        rows += [(float(start + i), 1000.0, 1) for i in range(10)]
        rows += [(float(start + 10 + i), current, 0) for i in range(90)]
    path = write(tmp_path / "sweep.csv", rows, "Timestamp(ms),Current(uA),GPI1")
    trace = Trace.read(path)

    steps = trace.windows("GPI1", gaps=True)
    assert steps == [(10, 100), (110, 200), (210, 300)]
    report = summarise(trace, steps, 0.0, 220.0)
    assert [round(w["mean_ua"]) for w in report["windows"]] == [90, 50, 20]


def _otii_folder(tmp_path, samples: list[tuple[float, float]], marker=None):
    """An Arc export as the instrument really writes it, pinned 2026-10-26.

    One folder a recording, one file a channel, `"Timestamp","Value"` in both,
    the timestamp in seconds and the value in the quantity's SI unit. The
    channel is named by the file and nowhere else.
    """
    folder = tmp_path / "recording"
    folder.mkdir()
    current = folder / "Main current - Arc.csv"
    current.write_text(
        '"Timestamp","Value"\n' + "".join(f"{t:.6f},{a:.8e}\n" for t, a in samples),
        encoding="utf-8",
    )
    if marker is not None:
        (folder / "GPI1 - Arc.csv").write_text(
            '"Timestamp","Value"\n' + "".join(f"{t:.6f},{v:g}\n" for t, v in marker),
            encoding="utf-8",
        )
    return folder


def test_an_arc_export_folder_reads_with_no_flags(tmp_path) -> None:
    """The headers say neither the quantity nor the unit, so the file name has
    to: amperes under `Main current`, seconds under a bare `Timestamp`."""
    folder = _otii_folder(tmp_path, [(i * 0.00025, 4.0e-06) for i in range(400)])
    assert main([str(folder)]) == 0
    trace = Trace.read(folder / "Main current - Arc.csv")
    assert trace.period_ms == 0.25
    assert round(st.median(trace.currents), 2) == 4.0  # microamps, from amperes


def test_the_marker_file_is_found_in_the_folder(tmp_path) -> None:
    samples = [(i * 0.00025, 4.0e-06 if i < 200 else 6.0e-03) for i in range(400)]
    marker = [(i * 0.001, 0.0 if i < 50 else 3.0) for i in range(100)]
    folder = _otii_folder(tmp_path, samples, marker)
    report = tmp_path / "report.json"
    assert main([str(folder), "--out", str(report)]) == 0
    payload = json.loads(report.read_text(encoding="utf-8"))
    assert len(payload["windows"]) == 1
    assert round(payload["windows"][0]["mean_ua"]) == 6000
