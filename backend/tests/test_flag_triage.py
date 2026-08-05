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


# --- stage 2: model output must be validated before it becomes an explanation

from finclone.pipeline.flag_triage import (
    LLM_RESOLUTIONS,
    NEEDS_REVIEW,
    _clean_verdicts,
    _keywords_for_concepts,
    _prompt_for,
)


def _payload(*verdicts):
    return {"verdicts": list(verdicts)}


def test_accepts_a_well_formed_verdict():
    got = _clean_verdicts(
        _payload({"id": 7, "resolution": "convention", "reason": "sign differs"}), {7})
    assert got == {7: ("convention", "sign differs")}


def test_drops_ids_we_did_not_ask_about():
    """The model must not be able to write a verdict onto an unrelated flag."""
    assert _clean_verdicts(
        _payload({"id": 999, "resolution": "convention", "reason": "x"}), {7}) == {}


def test_drops_unrecognised_resolution():
    assert _clean_verdicts(
        _payload({"id": 7, "resolution": "probably fine", "reason": "x"}), {7}) == {}


def test_drops_empty_reason():
    """A verdict with no reason is worse than no verdict — it looks explained."""
    for reason in ("", "   ", None):
        assert _clean_verdicts(
            _payload({"id": 7, "resolution": "convention", "reason": reason}), {7}) == {}


def test_resolution_is_case_insensitive():
    got = _clean_verdicts(
        _payload({"id": 7, "resolution": "  Convention ", "reason": "x"}), {7})
    assert got[7][0] == "convention"


def test_first_verdict_wins_on_duplicate_id():
    got = _clean_verdicts(_payload(
        {"id": 7, "resolution": "convention", "reason": "first"},
        {"id": 7, "resolution": "real_issue", "reason": "second"}), {7})
    assert got[7][1] == "first"


def test_string_id_is_coerced_not_rejected():
    assert 7 in _clean_verdicts(
        _payload({"id": "7", "resolution": "convention", "reason": "x"}), {7})


@pytest.mark.parametrize("payload", [None, [], "nope", {}, {"verdicts": None}])
def test_malformed_payload_yields_nothing(payload):
    assert _clean_verdicts(payload, {7}) == {}


def test_non_dict_entries_are_skipped():
    got = _clean_verdicts(_payload(
        "garbage", {"id": 7, "resolution": "convention", "reason": "x"}), {7})
    assert got == {7: ("convention", "x")}


def test_reason_truncated_to_the_column_width():
    got = _clean_verdicts(
        _payload({"id": 7, "resolution": "convention", "reason": "x" * 900}), {7})
    assert len(got[7][1]) == 512


def test_unexplained_is_an_available_verdict():
    """Stage 2 spans fiscal years whose figures aren't in the filing we supply,
    so the model needs an honest way to decline rather than inventing one."""
    assert "unexplained" in LLM_RESOLUTIONS
    assert "unexplained" in NEEDS_REVIEW
    assert "real_issue" in NEEDS_REVIEW
    assert "convention" not in NEEDS_REVIEW


# --- chunk pre-filter keywords -------------------------------------------

def test_concept_keywords_are_filing_prose_not_our_identifiers():
    """"capex" and "operating_cash_flow" appear nowhere in a filing."""
    kws = _keywords_for_concepts({"capex", "operating_cash_flow"})
    assert "capital expenditure" in kws
    assert "operating activities" in kws
    assert "operating_cash_flow" not in kws


def test_unknown_concept_falls_back_to_readable_form():
    assert _keywords_for_concepts({"some_new_concept"}) == ["some new concept"]


def test_keywords_are_deduplicated():
    kws = _keywords_for_concepts(["revenue", "revenue"])
    assert len(kws) == len(set(kws))


# --- prompt ---------------------------------------------------------------

class _Flag:
    def __init__(self, id, concept, fy, ours, ref, var):
        self.id, self.canonical_concept, self.fiscal_year = id, concept, fy
        self.our_value, self.reference_value, self.variance = ours, ref, var


def test_prompt_carries_every_flag_id_and_states_the_filing_limit():
    flags = [_Flag(1, "capex", 2024, 60_873_000, -59_173_000, 0.0287),
             _Flag(2, "revenue", 2019, 100.0, 160.0, 0.6)]
    prompt = _prompt_for("AAPL", {"form": "10-Q", "filed_date": "2026-05-01"},
                         "excerpt text", flags)
    assert "id=1" in prompt and "id=2" in prompt
    # The model must know it cannot see FY2019 in a 2026 10-Q.
    assert "only filing text available" in prompt
    assert "fiscal_year=2019" in prompt


# --- excerpt selection must degrade, not give up --------------------------

from finclone.pipeline.flag_triage import _STATEMENT_KEYWORDS, select_excerpt

_FILLER = "boilerplate legal text. " * 900  # ~21k chars, no financial vocabulary


def test_apple_term_debt_vocabulary_is_covered():
    """AAPL's 10-Q says "Term debt", never "long-term debt". Searching only for
    the latter scored 0 chunks and silently skipped the company."""
    assert "term debt" in _keywords_for_concepts({"long_term_debt"})


def test_concept_match_is_preferred():
    text = _FILLER + "Total term debt outstanding was 85,750. " + _FILLER
    excerpt = select_excerpt(text, {"long_term_debt"})
    assert "term debt outstanding" in excerpt


def test_falls_back_to_statement_pages_when_concept_misses():
    """A company whose flags all share one concept has no other keyword to fall
    back on, so a miss must widen the search rather than skip the company."""
    text = _FILLER + "CONSOLIDATED BALANCE SHEET (in thousands) Total assets 1,000" + _FILLER
    excerpt = select_excerpt(text, {"some_concept_absent_from_this_filing"})
    assert excerpt, "must not return empty — that skips the company silently"
    assert "consolidated balance sheet" in excerpt.lower()


def test_falls_back_to_start_of_filing_when_nothing_matches():
    text = _FILLER
    excerpt = select_excerpt(text, {"nonexistent_concept"})
    assert excerpt.startswith("boilerplate")


def test_truly_empty_text_returns_empty():
    """The one case where skipping is right: there is no filing text at all."""
    assert select_excerpt("", {"revenue"}) == ""
    assert select_excerpt("   \n ", {"revenue"}) == ""


def test_statement_keywords_are_generic_enough_to_be_a_fallback():
    for kw in _STATEMENT_KEYWORDS:
        assert kw == kw.lower(), "matching is done on lowercased text"
