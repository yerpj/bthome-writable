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

from tools.power_charge import (
    Trace,
    command_summary,
    commands,
    idle_floor,
    main,
    summarise,
)

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


def _events(plan: list[tuple[float, float, int]]) -> list[tuple[float, float]]:
    """Samples for a run of radio events: (interval_ms, length_ms, count)."""
    rows: list[tuple[float, float]] = []
    now = 0.0
    hot: list[tuple[float, float]] = []
    for interval, length, count in plan:
        for _ in range(count):
            hot.append((now, now + length))
            now += interval
    samples = int(now / 0.25)
    pending = iter(hot)
    event = next(pending, None)
    for index in range(samples):
        t = index * 0.25
        while event is not None and t >= event[1]:
            event = next(pending, None)
        inside = event is not None and event[0] <= t < event[1]
        rows.append((t / 1000.0, (2000.0 if inside else 4.0) * 1e-6))
    return rows


def test_a_connection_and_the_fast_window_after_it_are_read_apart(tmp_path) -> None:
    """The command recordings have no marker either, and three things to find
    in them: the idle interval, the connection at whatever interval the
    central negotiated, and the fast window the disconnection opens."""
    folder = _otii_folder(
        tmp_path,
        _events(
            [
                (2000.0, 6.0, 5),  # idle
                (45.0, 1.5, 10),  # one connection
                (100.0, 6.0, 40),  # the fast window after it
                (2000.0, 6.0, 5),  # idle again
            ]
        ),
    )
    runs = Trace.read(folder / "Main current - Arc.csv").phases()
    rates = [run["gap_ms"] for run in runs]
    assert [round(rate / 5) * 5 for rate in rates] == [2000, 45, 100, 2000]
    connection = runs[1]
    # Eleven, not ten: a run is a run of *gaps*, so the event that ends the
    # last connection gap is the first event of the fast window. The boundary
    # belongs to both runs and the charge of one event is not the figure
    # anything here quotes.
    assert connection["events"] == 11
    assert 400 < connection["duration_ms"] < 460
    # The fast window is measured, not taken from fastTimeout.
    assert 3900 < runs[2]["duration_ms"] < 4100


def test_a_run_of_two_events_is_not_a_run(tmp_path) -> None:
    folder = _otii_folder(tmp_path, _events([(2000.0, 6.0, 5), (45.0, 1.5, 2)]))
    runs = Trace.read(folder / "Main current - Arc.csv").phases()
    assert [round(run["gap_ms"] / 5) * 5 for run in runs] == [2000]


def test_a_power_up_spike_does_not_raise_the_burst_threshold(tmp_path) -> None:
    """The real trace of 2026-10-26 opens with 138 mA of boot. A threshold
    taken as a fraction of the peak landed at 6.9 mA and found none of the
    eighteen minutes of advertising events behind it."""
    samples = _events([(2000.0, 6.0, 6)])
    samples[0] = (samples[0][0], 0.138)  # 138 mA, one sample, at power-up
    folder = _otii_folder(tmp_path, samples)
    trace = Trace.read(folder / "Main current - Arc.csv")
    assert max(trace.currents) == 138000.0
    assert trace.burst_threshold() < 1500.0
    assert len(trace.bursts(trace.burst_threshold())) >= 6


def test_the_oscillator_calibration_is_not_a_radio_event(tmp_path) -> None:
    """A Puck.js recalibrates its RC oscillator every 8.000 s, 17 ms at 780 uA
    of peak. Counted as a radio event it splits an advertising run in two every
    eight seconds, which turned one clean sweep into 81 fragments."""
    rows = _events([(2000.0, 6.0, 20)])
    # Drop a calibration into the quiet between events, 780 uA for 17 ms.
    for index, (when, _value) in enumerate(rows):
        if 7.9 < when < 7.917 or 15.9 < when < 15.917:
            rows[index] = (when, 780e-6)
    folder = _otii_folder(tmp_path, rows)
    trace = Trace.read(folder / "Main current - Arc.csv")
    steps = trace.segments((2000,))
    assert len(steps) == 1, "one step, not three"
    assert steps[0]["label"] == 2000


def test_two_runs_at_one_interval_are_one_step(tmp_path) -> None:
    """A dropped event cuts a run; the step is still one step."""
    rows = _events([(100.0, 6.0, 12), (240.0, 6.0, 1), (100.0, 6.0, 12)])
    folder = _otii_folder(tmp_path, rows)
    steps = Trace.read(folder / "Main current - Arc.csv").segments((100, 200))
    assert [step["label"] for step in steps] == [100]


def test_radio_that_never_stops_is_a_phase_of_its_own(tmp_path) -> None:
    """A run is a run of gaps, which makes the reader blind to exactly one
    thing: a continuous block. Each command of 2026-10-26 carried a 0.19 s
    block at 3.9 mA, worth 740 uC and 40% of what a command costs, and it
    belonged to no run. The table came out 15% light and nothing said so."""
    rows = _events([(2000.0, 6.0, 4)])
    # A solid 100 ms of radio, right after the fourth advertising event.
    block_from = 6.2
    rows = [
        (when, 4000e-6 if block_from <= when < block_from + 0.1 else value)
        for when, value in rows
    ]
    assert any(value == 4000e-6 for _when, value in rows)
    folder = _otii_folder(tmp_path, rows)
    trace = Trace.read(folder / "Main current - Arc.csv")
    runs = trace.phases()
    solid = [run for run in runs if run["gap_ms"] == 0.0]
    assert solid, "the continuous block has to come back as a phase"
    # Its charge, not its mean: a solid phase is the stretch no run covered,
    # so it carries the block plus whatever idle sits either side of it, and
    # the charge is the figure a per-command cost is taken from. 100 ms at
    # 4 mA is 400 uC.
    assert max(run["charge_uc"] for run in solid) > 380.0

    # And the phases now account for essentially all of the charge, which is
    # the check that would have caught this without a trip to the bench.
    assert trace.coverage(runs) > 0.95


def _phase(label: str, start_ms: float, duration_ms: float, mean_ua: float) -> dict:
    """One window of a `--phases` report, as `summarise` writes it."""
    return {
        "start_ms": start_ms,
        "duration_ms": duration_ms,
        "mean_ua": mean_ua,
        "max_ua": mean_ua,
        "charge_uc": mean_ua * duration_ms / 1000.0,
        "excess_uc": mean_ua * duration_ms / 1000.0,
        "label": label,
    }


def _one_command(
    at_ms: float, solid_ms: float, window_ms: float = 30000.0
) -> list[dict]:
    """The four phases a command is, in the order the trace holds them."""
    return [
        _phase("7.5", at_ms, 60.0, 1200.0),
        _phase("0.0", at_ms + 60.0, solid_ms, 3600.0),
        _phase("7.5", at_ms + 60.0 + solid_ms, 1800.0, 600.0),
        _phase("104.5", at_ms + 60.0 + solid_ms + 1800.0, window_ms, 150.0),
    ]


def _recording(solid_ms: float = 80.0) -> list[dict]:
    """A boot connection, idle, and three commands 45 s apart."""
    windows = [_phase("0.0", 0.0, 15000.0, 565.0)]
    windows += [_phase("104.5", 15000.0, 30000.0, 150.0)]
    windows += [_phase("2005.0", 45000.0, 50000.0, 15.0)]
    at = 95000.0
    for _ in range(3):
        windows += _one_command(at, solid_ms)
        at = windows[-1]["start_ms"] + windows[-1]["duration_ms"]
        windows += [_phase("2005.0", at, 13000.0, 15.0)]
        at += 13000.0
    return windows


def test_the_floor_comes_from_the_long_idle_phases() -> None:
    """Not from the scraps. A command recording holds one-event stretches of
    idle between its phases, and their mean is the event rather than the
    device: a floor taken from those would be hundreds of microamps and every
    per-command charge would come out negative."""
    windows = _recording()
    windows.append(_phase("2005.0", 500000.0, 70.0, 790.0))
    assert idle_floor(windows) == pytest.approx(15.0)


def test_a_recording_with_no_idle_in_it_refuses_rather_than_guesses() -> None:
    windows = [_phase("104.5", 0.0, 30000.0, 150.0)]
    with pytest.raises(SystemExit, match="no idle phase"):
        idle_floor(windows)


def test_the_boot_connection_is_flagged_and_left_out_of_the_medians() -> None:
    """A recording that starts before the board does opens with Home Assistant
    connecting to a device it has never seen, which costs service discovery
    once. Counting it as a command put recording 2's first three connections
    1000 uC above the other six."""
    found = commands(_recording())
    assert [row["boot"] for row in found] == [True, False, False, False]
    summary = command_summary(found, idle_floor(_recording()))
    assert summary["n"] == 3
    assert summary["boot_connection_uc"] == pytest.approx(8250.0, rel=0.01)


def test_a_command_is_its_connection_plus_the_window_it_opens() -> None:
    found = commands(_recording(solid_ms=80.0))
    row = found[1]
    # 60 ms at 1200 uA, 80 at 3600, 1800 at 600, all above a 15 uA floor.
    assert row["solid_ms"] == pytest.approx(80.0)
    assert row["solid_uc"] == pytest.approx(288.0, rel=0.01)
    assert row["link_ms"] == pytest.approx(1800.0)
    assert row["connection_uc"] == pytest.approx(
        72.0 + 288.0 + 1080.0 - 15.0 * 1.94, rel=0.01
    )
    assert row["window_s"] == pytest.approx(30.0)
    assert row["window_uc"] == pytest.approx(4500.0 - 450.0, rel=0.01)
    assert row["all_in_uc"] == pytest.approx(
        row["connection_uc"] + row["window_uc"], rel=1e-6
    )
    assert not row["window_truncated"]


def test_pinning_shows_up_as_the_solid_block_and_nowhere_else() -> None:
    """The finding of recording 3: one statement different on the device and
    the opening burst of unbroken radio goes from 190 ms to 79 ms, with the
    link after it and the fast window unchanged. The grouping has to put that
    difference in one column, or the comparison is not readable."""
    auto = command_summary(commands(_recording(190.0)), 15.0)
    pinned = command_summary(commands(_recording(80.0)), 15.0)
    assert auto["median_link_uc"] == pytest.approx(pinned["median_link_uc"])
    assert auto["median_window_uc"] == pytest.approx(pinned["median_window_uc"])
    # The connection difference is the solid block's, less the idle the longer
    # block would have spent anyway: a charge above the floor, not a charge.
    saved = auto["median_solid_uc"] - pinned["median_solid_uc"]
    longer_s = (auto["median_solid_ms"] - pinned["median_solid_ms"]) / 1000.0
    assert auto["median_connection_uc"] - pinned[
        "median_connection_uc"
    ] == pytest.approx(saved - 15.0 * longer_s, abs=0.1)  # the stored rounding


def test_a_command_inside_another_s_window_truncates_it() -> None:
    """Two of recording 3's ten commands arrived 20 s late and landed inside
    the fast window their predecessor was still spending, which is the
    saturation the reference table predicts. Such a window is not 30 s and its
    charge must not be medianed with the ones that are."""
    windows = _recording()
    windows += _one_command(500000.0, 80.0, window_ms=20810.0)
    found = commands(windows)
    assert found[-1]["window_truncated"]
    summary = command_summary(found, idle_floor(windows))
    assert summary["n"] == 4
    assert summary["n_full_window"] == 3
    assert summary["median_window_s"] == pytest.approx(30.0)
