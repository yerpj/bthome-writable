"""The regression guard's policy, tested without a radio.

`compare()` and `summarise()` are the parts that decide whether a release goes
out, so they are the parts that must not be trusted to a hardware run to
exercise. The thresholds themselves are a judgement, and the tests below pin the
judgement rather than the arithmetic: what counts as a regression, what counts as
noise, and what counts as the bench having changed under the measurement.
"""

from __future__ import annotations

from tools.regression import compare, summarise

BASELINE = {
    "first_median_s": 2.0,
    "first_p90_s": 4.0,
    "repeat_median_s": 0.35,
    "repeat_p90_s": 0.60,
    "write_median_ms": 36.0,
    "delivered_fraction": 1.0,
    "direct_fraction": 1.0,
}


def verdicts(measured: dict) -> dict[str, str]:
    return {
        check.name: check.verdict
        for check in compare(BASELINE, {**BASELINE, **measured})
    }


def test_an_unchanged_run_passes() -> None:
    assert set(verdicts({}).values()) == {"ok"}


def test_ordinary_noise_is_not_a_regression() -> None:
    """Two runs of the same build differed by 30-50 % at the slow paliers
    (D-061). A guard that fails on that is a guard that gets switched off."""
    assert verdicts({"first_median_s": 2.9})["first command, median"] == "ok"
    assert verdicts({"repeat_median_s": 0.5})["repeated command, median"] == "ok"


def test_a_real_slowdown_is_caught() -> None:
    """The shape of the D-059 regression in reverse: a repeated command going
    from a third of a second back to the 1.9 s the batching's pause cost."""
    assert verdicts({"repeat_median_s": 1.9})["repeated command, median"] == "regressed"
    assert verdicts({"first_median_s": 6.0})["first command, median"] == "regressed"


def test_a_small_baseline_is_not_guarded_to_within_the_noise() -> None:
    """A floor, not just a factor: 0.35 s times 1.6 is 0.56, and a repeated
    command's own spread reaches past that (D-062, worst of eighty 1.94 s)."""
    assert verdicts({"repeat_median_s": 0.70})["repeated command, median"] == "ok"
    assert (
        verdicts({"repeat_median_s": 0.95})["repeated command, median"] == "regressed"
    )


def test_losing_commands_is_a_regression() -> None:
    assert verdicts({"delivered_fraction": 0.85})["delivered"] == "regressed"
    assert verdicts({"delivered_fraction": 0.95})["delivered"] == "ok"


def test_retrying_more_often_is_a_regression() -> None:
    """A tenth of first commands needed a retry on this bench (D-061); losing
    another fifth to it is a change in behaviour, not weather."""
    assert (
        verdicts({"direct_fraction": 0.7})["connected without a retry"] == "regressed"
    )
    assert verdicts({"direct_fraction": 0.9})["connected without a retry"] == "ok"


def test_a_suspiciously_fast_run_is_flagged_rather_than_passed() -> None:
    """Through a proxy that reuses a link, first commands came back faster than
    catching an advertisement allows (D-054). That is not an improvement to
    celebrate, it is a bench that stopped measuring the same thing."""
    assert verdicts({"first_median_s": 0.2})["first command, median"] == "suspicious"
    assert not any(
        check.failed for check in compare(BASELINE, {**BASELINE, "first_median_s": 0.2})
    )


def sample(total_ms: float, *, connect_ms: float = 100.0, **extra) -> dict:
    return {
        "total_ms": total_ms,
        "connect_ms": connect_ms,
        "write_ms": 36.0,
        "fast_window_ok": True,
        **extra,
    }


def test_a_summary_counts_what_did_not_arrive() -> None:
    first = [sample(2000.0), {"failed": True}]
    got = summarise(first, [sample(350.0)])

    assert got["commands"] == 3
    assert got["delivered_fraction"] == round(2 / 3, 3)
    assert got["first_median_s"] == 2.0
    assert got["repeat_median_s"] == 0.35


def test_a_retried_connection_does_not_count_as_a_direct_one() -> None:
    """The far group of D-061: above 25 s the link was opened on a second
    attempt, which is the receiver's retry policy showing, not the interval."""
    got = summarise([sample(37000.0, connect_ms=36900.0), sample(2000.0)], [])
    assert got["direct_fraction"] == 0.5


def test_a_sample_on_the_wrong_side_of_the_fast_window_is_excluded_and_counted() -> (
    None
):
    """It measures the other case under this one's label, so it must not be
    averaged in -- and the run must say so rather than look clean."""
    got = summarise([sample(2000.0), sample(0.3, fast_window_ok=False)], [])

    assert got["samples_on_the_wrong_side_of_the_fast_window"] == 1
    assert got["first_median_s"] == 2.0
