from finclone.pipeline.crossref import variance


def test_variance_identical_values():
    assert variance(100.0, 100.0) == 0.0


def test_variance_sign_conventions_ignored():
    # SimFin reports capex negative; XBRL positive — magnitudes match => 0
    assert variance(500.0, -500.0) == 0.0


def test_variance_relative_difference():
    assert abs(variance(101.0, 100.0) - 0.01) < 1e-9
    assert variance(150.0, 100.0) == 0.5


def test_variance_zero_reference():
    assert variance(0.0, 0.0) == 0.0
    assert variance(5.0, 0.0) == float("inf")


# --- triage preservation across a flag refresh -----------------------------
# crossref_ticker refreshes a company's flags wholesale, and _RECHECK_DAYS
# brings every company back every 14 days. Without carry-forward that deletes
# the entire explained queue — including stage-2 verdicts that cost a model
# call each — on every sweep.

from finclone.pipeline.crossref import preserved_triage

_TRIAGED = (100.0, -101.0, "convention", "signs differ", "rule", True, True)


def test_verdict_survives_when_numbers_unchanged():
    kept = preserved_triage(_TRIAGED, 100.0, -101.0)
    assert kept == {"resolution": "convention", "reason": "signs differ",
                    "resolved_by": "rule", "reviewed": True, "resolved": True}


def test_verdict_reset_when_our_value_moved():
    """The disagreement itself changed, so the old explanation no longer
    describes it — carrying it forward would assert something untrue."""
    assert preserved_triage(_TRIAGED, 250.0, -101.0)["resolution"] is None


def test_verdict_reset_when_reference_value_moved():
    assert preserved_triage(_TRIAGED, 100.0, -900.0)["resolution"] is None


def test_reset_clears_every_field_not_just_resolution():
    reset = preserved_triage(_TRIAGED, 250.0, -101.0)
    assert reset == {"resolution": None, "reason": None, "resolved_by": None,
                     "reviewed": False, "resolved": False}


def test_new_flag_starts_untriaged():
    assert preserved_triage(None, 100.0, -101.0)["resolution"] is None
    assert preserved_triage(None, 100.0, -101.0)["reviewed"] is False


def test_returns_a_fresh_dict_each_call():
    """Callers splat this into a model constructor; a shared dict would let one
    flag's mutation leak into the next."""
    a = preserved_triage(None, 1.0, 2.0)
    a["resolution"] = "mutated"
    assert preserved_triage(None, 1.0, 2.0)["resolution"] is None
