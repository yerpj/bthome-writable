"""The reference table's arithmetic, which is the part that gets quoted.

The table of §23 is computed from four measured coefficients rather than from
49 recordings, so the computation is the thing that has to be right: a wrong
term here is a wrong battery life on the module page, and nobody checking their
own device would catch it.
"""

from __future__ import annotations

import pytest

from tools.power_table import Model, fit, table

# Round numbers rather than plausible ones, so every expectation below can be
# checked by hand: 9 uC an advertising event is 45 uA at a 200 ms interval.
MODEL = Model(
    floor_ua=45.0, adv_charge_uc=9.0, command_charge_uc=120.0, fast_timeout_s=30.0
)


def test_a_device_nobody_writes_to_is_the_floor_plus_advertising() -> None:
    assert MODEL.current_ua(200, 0) == 45.0 + 45.0
    assert MODEL.current_ua(1000, 0) == 45.0 + 9.0
    assert MODEL.current_ua(10000, 0) == 45.0 + 0.9


def test_one_command_a_minute_holds_the_window_open_half_the_time() -> None:
    assert MODEL.fast_share(1) == 0.5
    terms = MODEL.terms(2000, 1)
    # Half a minute at 100 ms is 90 uA halved; the other half is 4.5 uA halved.
    assert terms["fast_window_ua"] == 45.0
    assert terms["advertising_ua"] == 2.25
    # One command of 120 uC a minute is 2 uA.
    assert terms["commands_ua"] == 2.0
    assert terms["total_ua"] == 94.25


def test_above_two_a_minute_the_interval_stops_showing() -> None:
    """The finding the table exists to make visible: a 30 s fast window that
    never closes, after which `fastTimeout` is the lever and `interval` is
    not."""
    assert MODEL.fast_share(2) == 1.0
    assert MODEL.saturating_rate() == 2.0
    for rate in (2, 3, 4, 6):
        assert MODEL.current_ua(200, rate) == MODEL.current_ua(10000, rate)
        assert MODEL.terms(5000, rate)["advertising_ua"] == 0.0


def test_the_commands_still_cost_above_the_saturation() -> None:
    assert MODEL.current_ua(2000, 6) - MODEL.current_ua(2000, 2) == 8.0


def test_a_longer_fast_window_saturates_sooner() -> None:
    patient = Model(45.0, 9.0, 120.0, fast_timeout_s=60.0)
    assert patient.saturating_rate() == 1.0
    assert patient.fast_share(1) == 1.0
    brisk = Model(45.0, 9.0, 120.0, fast_timeout_s=5.0)
    assert brisk.saturating_rate() == 12.0


def test_a_battery_life_is_the_mean_divided_into_the_capacity() -> None:
    # 90 uA into 220 mAh is 2444 hours, which is 102 days.
    assert round(MODEL.life_days(200, 0, 220.0)) == 102


def test_the_table_has_a_row_per_interval_and_a_column_per_rate() -> None:
    rendered = table(MODEL).splitlines()
    assert rendered[2].count("|") == 8  # one label column and six rates
    assert len([line for line in rendered if line.startswith("| ")]) == 8
    assert "| 200 ms |" in rendered[4]
    assert "| 10 s |" in rendered[-1]


def test_the_life_table_says_days_and_names_the_battery() -> None:
    rendered = table(MODEL, capacity_mah=220.0)
    assert rendered.startswith("**Days on 220 mAh**")


def test_the_coefficients_come_out_of_a_swept_report() -> None:
    """A sweep measured at four intervals, with a floor of 45 uA and 9 uC an
    event, has to fit back to exactly that."""
    report = {
        "windows": [
            {"label": label, "mean_ua": 45.0 + 9.0 / (label / 1000.0)}
            for label in (200, 1000, 3200, 10000)
        ]
    }
    fitted = fit(report)
    assert fitted["floor_ua"] == 45.0
    assert fitted["adv_charge_uc"] == 9.0
    assert fitted["worst_residual_ua"] == 0.0
    assert fitted["points"] == 4


def test_a_sweep_of_one_point_cannot_be_fitted() -> None:
    with pytest.raises(SystemExit, match="at least two"):
        fit({"windows": [{"label": 1000, "mean_ua": 54.0}]})


def test_a_sensor_that_moves_adds_its_rebuilds() -> None:
    """The one term the protocol does not set: a device advertising a value
    that moves pays a rebuild each time, which §4 measures in milliseconds and
    arm E measures in charge."""
    with_sensor = Model(45.0, 9.0, 120.0, rebuild_charge_uc=600.0, rebuilds_per_min=2.0)
    # 600 uC twice a minute is 20 uA, on top of the same floor and advertising.
    assert with_sensor.current_ua(2000, 0) - MODEL.current_ua(2000, 0) == 20.0
    assert with_sensor.terms(2000, 0)["rebuilds_ua"] == 20.0
    assert MODEL.terms(2000, 0)["rebuilds_ua"] == 0.0
