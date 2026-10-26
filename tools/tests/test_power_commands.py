"""The spacing of the command runs, which is the one thing that can invalidate
a per-command charge without looking wrong.

`fastTimeout` is 30 s. A command sent sooner than that after the previous one
is measured from inside the fast window it opened, so the charge attributed to
a command would depend on the spacing rather than on the command.
"""

from __future__ import annotations

import pytest

from tools.power_commands import LEAD_IN_S, schedule


def test_the_commands_are_spaced_past_the_fast_window() -> None:
    when = schedule(10, 45.0)
    assert len(when) == 10
    assert when[0] == LEAD_IN_S
    gaps = [when[i + 1] - when[i] for i in range(len(when) - 1)]
    assert all(gap == 45.0 for gap in gaps)
    assert all(gap > 30.0 for gap in gaps), "past fastTimeout, or it is not idle"


def test_a_lead_in_leaves_idle_to_measure_the_floor_against() -> None:
    assert schedule(2, 45.0, lead_in=20.0) == [20.0, 65.0]


def test_the_checks_of_recording_four_are_allowed_to_saturate() -> None:
    """One and four commands a minute is the saturation itself, so the spacing
    is deliberately inside the fast window there."""
    assert schedule(4, 15.0, 0.0) == [0.0, 15.0, 30.0, 45.0]


def test_a_run_of_nothing_is_refused() -> None:
    with pytest.raises(ValueError, match="measures nothing"):
        schedule(0, 45.0)
    with pytest.raises(ValueError, match="spacing"):
        schedule(5, 0.0)
