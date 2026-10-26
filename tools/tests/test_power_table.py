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
    floor_ua=45.0,
    adv_charge_uc=9.0,
    command_charge_uc=120.0,
    command_seconds=6.0,
    fast_timeout_s=30.0,
)
"""6 s a command rather than the measured 2.34, for the same reason the other
coefficients are round: a connection that is a tenth of a minute makes every
share below checkable by hand."""

PUCK = Model(
    floor_ua=7.35,
    adv_charge_uc=14.194,
    command_charge_uc=1810.0,
    command_seconds=2.34,
)
"""The Puck.js as section 23 measured it, for the claims that are about the
device rather than about the arithmetic. 1810 uC and 2.34 s are the medians of
39 commands across recordings 2 and 4."""


def test_a_device_nobody_writes_to_is_the_floor_plus_advertising() -> None:
    assert MODEL.current_ua(200, 0) == 45.0 + 45.0
    assert MODEL.current_ua(1000, 0) == 45.0 + 9.0
    assert MODEL.current_ua(10000, 0) == 45.0 + 0.9


def test_one_command_a_minute_holds_the_window_open_half_the_time() -> None:
    assert MODEL.fast_share(1) == 0.5
    assert MODEL.connected_share(1) == 0.1
    terms = MODEL.terms(2000, 1)
    # Half a minute at 100 ms is 90 uA halved. Of the other half, 6 s are spent
    # on the link and advertise at neither rate, so 4.5 uA gets 0.4 and not 0.5.
    assert terms["fast_window_ua"] == 45.0
    assert terms["advertising_ua"] == 1.8
    # One command of 120 uC a minute is 2 uA.
    assert terms["commands_ua"] == 2.0
    assert terms["total_ua"] == 93.8


def test_a_second_on_the_link_is_not_a_second_of_fast_window() -> None:
    """Recording 4's four-a-minute cell came back 14% under the table, and
    this is why: the model billed the whole period at `fastInterval` and then
    added the command on top, so the 2.3 s each command spends connected was
    charged twice. A connection is not a fast window. At one command a minute
    the double count hides in the idle term; at four it is 2.3 s of 15."""
    # Nine seconds a minute on the link leaves 51 for the window, not 60.
    assert MODEL.connected_share(1.5) == pytest.approx(0.15)
    assert MODEL.fast_share(1.5) == pytest.approx(0.75)
    # And at saturation the two shares fill the minute between them.
    for rate in (2, 3, 4, 6):
        assert MODEL.fast_share(rate) + MODEL.connected_share(rate) == pytest.approx(
            1.0
        )


def test_above_the_saturation_the_interval_stops_showing() -> None:
    """The finding the table exists to make visible: a 30 s fast window that
    never closes, after which `fastTimeout` is the lever and `interval` is
    not."""
    # 60 / (30 + 6), not 60 / 30: a command's own seconds count against the
    # minute it has to fill.
    assert MODEL.saturating_rate() == pytest.approx(60.0 / 36.0)
    for rate in (2, 3, 4, 6):
        assert MODEL.current_ua(200, rate) == MODEL.current_ua(10000, rate)
        assert MODEL.terms(5000, rate)["advertising_ua"] == 0.0


def test_the_commands_still_cost_above_the_saturation() -> None:
    """On the measured device, because the direction depends on the
    coefficients: a link that is cheaper per second than advertising at
    `fastInterval` would make more commands cost less, and the Puck's is not --
    1810 uC over 2.34 s is 773 uA against the fast window's 142."""
    assert PUCK.current_ua(2000, 6) > PUCK.current_ua(2000, 2)
    # Four more commands a minute are 4 * 1810 / 60 = 120.7 uA of connection,
    # less the fast advertising those connections displace: 4 * 2.34 s of the
    # minute at 141.9 uA, which is 22.1 uA back.
    assert PUCK.current_ua(2000, 6) - PUCK.current_ua(2000, 2) == pytest.approx(
        4.0 * 1810.0 / 60.0 - 4.0 * 2.34 / 60.0 * 14.194 / 0.1, rel=0.01
    )


def test_the_two_measured_cells_of_recording_four() -> None:
    """The checks of section 23, which are the only reason to trust any other
    cell. One command a minute measured 116.90 uA over 600 s and four a minute
    236.45 over 300 s, both at a 2 s idle interval on a sealed Puck.js. The
    model is asked for 5%, not for 1%: a command's charge is mostly the central
    holding the link open, and that varied by 27% between the two cells of this
    same recording."""
    assert PUCK.current_ua(2000, 1) == pytest.approx(116.90, rel=0.05)
    assert PUCK.current_ua(2000, 4) == pytest.approx(236.45, rel=0.05)
    # And the thing the fix was for: billing the connection's own seconds to
    # the fast window as well put the four-a-minute cell 14% out.
    double_counted = Model(
        floor_ua=7.35,
        adv_charge_uc=14.194,
        command_charge_uc=1810.0,
        command_seconds=0.0,
    )
    assert double_counted.current_ua(2000, 4) / 236.45 > 1.1


def test_a_longer_fast_window_saturates_sooner() -> None:
    patient = Model(45.0, 9.0, 120.0, command_seconds=0.0, fast_timeout_s=60.0)
    assert patient.saturating_rate() == 1.0
    assert patient.fast_share(1) == 1.0
    brisk = Model(45.0, 9.0, 120.0, command_seconds=0.0, fast_timeout_s=5.0)
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


def test_the_stretch_before_the_sweep_starts_is_dropped() -> None:
    """A device-driven sweep leaves one gap more than it has steps: the minute
    before its first marker pulse, which holds the sketch load and the fast
    window the console's disconnect opened. The run sheet labels it `-`."""
    report = {
        "windows": [{"label": "-", "mean_ua": 310.0}]
        + [
            {"label": label, "mean_ua": 45.0 + 9.0 / (label / 1000.0)}
            for label in (200, 1000, 3200, 10000)
        ]
    }
    fitted = fit(report)
    assert fitted["points"] == 4
    assert fitted["floor_ua"] == 45.0
    assert fitted["worst_residual_ua"] == 0.0
