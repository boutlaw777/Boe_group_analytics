"""Stage-1 maturity-split reconciliation.

The AAPL long-term-debt flags (FY2023-FY2025) sat open in the review queue
because they look like a data error and are actually a definitional split: we
report term debt non-current only, the reference reports the total. This rule
settles that case by arithmetic, so it must be exactly as certain as the sign
rule beside it — reconcile or defer, never approximate.
"""

from finclone.pipeline.flag_triage import (
    _MATURITY_SPLIT_TOLERANCE,
    classify_maturity_split,
)


class _Flag:
    """Minimal stand-in for the ValidationFlag columns the rule reads."""

    def __init__(self, our_value, reference_value, concept="long_term_debt",
                 fiscal_year=2025):
        self.canonical_concept = concept
        self.fiscal_year = fiscal_year
        self.our_value = our_value
        self.reference_value = reference_value


# --- the production rows this rule exists for ------------------------------

# Apple's own 10-K tags both figures: LongTermDebtNoncurrent (ours) and
# LongTermDebt (the total the reference publishes). Current portions come from
# the same filings.
AAPL = {
    2025: (78_328_000_000, 90_678_000_000, 12_350_000_000),
    2024: (85_750_000_000, 96_662_000_000, 10_912_000_000),
    2023: (95_281_000_000, 105_103_000_000, 9_822_000_000),
}


def test_every_open_aapl_year_reconciles():
    for year, (ours, reference, current) in AAPL.items():
        flag = _Flag(ours, reference, fiscal_year=year)
        verdict = classify_maturity_split(
            flag, {("long_term_debt_current", year): current})
        assert verdict is not None, f"FY{year} should reconcile"
        resolution, reason = verdict
        assert resolution == "convention"
        assert "Maturity-split" in reason
        assert "no action needed" in reason.lower()


def test_reason_shows_the_arithmetic():
    """An analyst closing the queue item has to be able to check the claim
    without reopening the filing."""
    ours, reference, current = AAPL[2025]
    _, reason = classify_maturity_split(
        _Flag(ours, reference), {("long_term_debt_current", 2025): current})
    assert "78,328,000,000" in reason
    assert "12,350,000,000" in reason
    assert "90,678,000,000" in reason


# --- certainty: it must defer rather than guess ----------------------------

def test_near_miss_defers():
    """A component that almost closes the gap is not evidence of a split — the
    remaining difference would be a second, unexplained fact."""
    assert classify_maturity_split(
        _Flag(78_328_000_000, 90_678_000_000),
        {("long_term_debt_current", 2025): 9_000_000_000},
    ) is None


def test_missing_component_defers():
    assert classify_maturity_split(_Flag(78_328_000_000, 90_678_000_000), {}) is None


def test_component_from_another_year_is_not_used():
    """Reconciling FY2025 against FY2024's current portion would produce a
    confident verdict from the wrong number."""
    assert classify_maturity_split(
        _Flag(78_328_000_000, 90_678_000_000, fiscal_year=2025),
        {("long_term_debt_current", 2024): 12_350_000_000},
    ) is None


def test_unsplittable_concept_defers():
    assert classify_maturity_split(
        _Flag(100.0, 150.0, concept="revenue"),
        {("long_term_debt_current", 2025): 50.0},
    ) is None


def test_zero_reference_defers():
    assert classify_maturity_split(
        _Flag(100.0, 0.0), {("long_term_debt_current", 2025): 50.0}) is None


def test_tolerance_boundary_is_inclusive():
    reference = 100_000.0
    ours = 60_000.0
    current = 40_000.0 - reference * _MATURITY_SPLIT_TOLERANCE
    assert classify_maturity_split(
        _Flag(ours, reference), {("long_term_debt_current", 2025): current}) is not None


def test_falls_back_through_component_combinations():
    """A filer whose total folds in commercial paper still reconciles, and the
    reason names only the components actually needed."""
    verdict = classify_maturity_split(
        _Flag(60_000.0, 100_000.0),
        {("long_term_debt_current", 2025): 30_000.0,
         ("commercial_paper", 2025): 10_000.0},
    )
    assert verdict is not None
    assert "commercial_paper" in verdict[1]


def test_smallest_sufficient_combination_wins():
    """When the current portion alone explains the total, commercial paper must
    not be dragged into the explanation."""
    verdict = classify_maturity_split(
        _Flag(60_000.0, 100_000.0),
        {("long_term_debt_current", 2025): 40_000.0,
         ("commercial_paper", 2025): 5_000.0},
    )
    assert verdict is not None
    assert "commercial_paper" not in verdict[1]
