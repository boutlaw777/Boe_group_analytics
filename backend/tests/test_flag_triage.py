"""Stage-1 flag triage: arithmetic rules must be certain or silent."""

import pytest

from finclone.pipeline.flag_triage import (
    _CONVENTION_MAX_VARIANCE,
    _IMMATERIAL_MAX_VARIANCE,
    classify,
)


def _resolution(*args):
    verdict = classify(*args)
    return verdict[0] if verdict else None


# --- convention (opposite signs, magnitudes agree) -------------------------

def test_real_capex_flag_from_production():
    """The row that motivated this module: SimFin books capex as a negative
    cash outflow, we store XBRL's positive PaymentsToAcquire*. Same number."""
    verdict = classify(60_873_000, -59_173_000, 0.0287)
    assert verdict is not None
    resolution, reason = verdict
    assert resolution == "convention"
    assert "opposite signs" in reason
    assert "no action needed" in reason.lower()


def test_convention_both_directions():
    assert _resolution(100.0, -101.0, 0.01) == "convention"
    assert _resolution(-100.0, 101.0, 0.01) == "convention"


def test_convention_boundary_is_inclusive():
    assert _resolution(100.0, -105.0, _CONVENTION_MAX_VARIANCE) == "convention"


def test_sign_flip_with_large_gap_is_deferred_not_claimed():
    """The sign is explained but the magnitude gap is a second, unexplained
    fact — calling the flag resolved would be wrong."""
    assert _resolution(100.0, -250.0, 0.60) is None


# --- immaterial (same sign, tiny gap) -------------------------------------

def test_immaterial_same_sign_small_gap():
    verdict = classify(1_000_000.0, 1_015_000.0, 0.015)
    assert verdict is not None
    assert verdict[0] == "immaterial"
    assert "rounding" in verdict[1].lower()


def test_immaterial_boundary_is_inclusive():
    assert _resolution(100.0, 102.0, _IMMATERIAL_MAX_VARIANCE) == "immaterial"


def test_same_sign_large_gap_is_deferred():
    assert _resolution(100.0, 160.0, 0.375) is None
    assert _resolution(-100.0, -160.0, 0.375) is None


def test_immaterial_threshold_is_tighter_than_convention():
    """A same-sign 4% gap must NOT be called immaterial just because 4% would
    pass the convention threshold — the two rules have different bars."""
    assert _resolution(100.0, 104.0, 0.04) is None


# --- refuses to guess -----------------------------------------------------

@pytest.mark.parametrize("ours,ref,var", [
    (None, 100.0, 0.01),
    (100.0, None, 0.01),
    (100.0, 100.0, None),
])
def test_missing_inputs_defer(ours, ref, var):
    assert classify(ours, ref, var) is None


def test_zero_on_either_side_defers():
    """A zero makes the sign test and the ratio meaningless — crossref records
    variance as inf when the reference is 0."""
    assert classify(0.0, 100.0, 1.0) is None
    assert classify(100.0, 0.0, float("inf")) is None
    assert classify(0.0, 0.0, 0.0) is None


def test_non_finite_variance_defers():
    assert classify(100.0, -100.0, float("inf")) is None
    assert classify(100.0, -100.0, float("nan")) is None


def test_negative_variance_is_treated_as_magnitude():
    """variance is stored as a magnitude, but defend against a signed value
    reaching us rather than silently mis-bucketing the flag."""
    assert _resolution(100.0, -101.0, -0.01) == "convention"


# --- output contract ------------------------------------------------------

def test_reason_fits_the_column():
    """reason is String(512); a truncated explanation would be worse than none."""
    for args in [(1.234e15, -1.235e15, 0.0008), (-9.87e14, -9.9e14, 0.003)]:
        verdict = classify(*args)
        assert verdict is not None
        assert len(verdict[1]) <= 512


def test_reason_quotes_both_values():
    _, reason = classify(60_873_000, -59_173_000, 0.0287)
    assert "60,873,000" in reason
    assert "59,173,000" in reason


def test_resolution_is_from_the_declared_set():
    from finclone.pipeline.flag_triage import RULE_RESOLUTIONS
    for args in [(100.0, -101.0, 0.01), (100.0, 101.0, 0.01)]:
        assert classify(*args)[0] in RULE_RESOLUTIONS
