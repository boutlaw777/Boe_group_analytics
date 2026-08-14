"""Per-number validation provenance, and alerting when the queue gains an item.

Both come from the same QA finding: the platform *was* checking numbers and
holding disputed ones, but neither fact reached anyone. A held figure nobody is
told about, and a published figure with no visible check, are indistinguishable
from unchecked data.
"""

from datetime import date

from finclone.api.main import _validation_status
from finclone.pipeline.crossref import COMPARABLE_CONCEPTS
from finclone.pipeline.notify import NewFlag, format_message

CHECKED = date(2026, 8, 11)


# --- provenance per number -------------------------------------------------

def test_compared_and_clean_is_agreed():
    assert _validation_status("revenue", 2025, CHECKED, set()) == "agreed"


def test_open_flag_wins_over_a_clean_run():
    """The company was checked, but this specific value is disputed."""
    assert _validation_status(
        "long_term_debt", 2025, CHECKED, {("long_term_debt", 2025)}) == "flagged"


def test_flag_on_another_year_does_not_taint_this_one():
    assert _validation_status(
        "long_term_debt", 2024, CHECKED, {("long_term_debt", 2025)}) == "agreed"


def test_concept_the_reference_does_not_carry_is_never_claimed_as_agreed():
    """The reference source covers part of our taxonomy. Reporting an
    uncomparable concept as 'agreed' would claim verification that never
    happened — the exact failure mode this whole feature exists to prevent."""
    assert "sga_expense" not in COMPARABLE_CONCEPTS
    assert _validation_status("sga_expense", 2025, CHECKED, set()) == "not_compared"


def test_never_cross_referenced_company():
    assert _validation_status("revenue", 2025, None, set()) == "not_checked"


def test_uncomparable_concept_reports_why_even_when_unchecked():
    """'not_compared' is more specific than 'not_checked' and stays true
    regardless of whether the company has been swept."""
    assert _validation_status("sga_expense", 2025, None, set()) == "not_compared"


def test_comparable_set_tracks_the_field_map():
    """Derived from the SimFin field map, so it cannot drift from what is
    actually compared."""
    assert {"revenue", "operating_income", "long_term_debt"} <= COMPARABLE_CONCEPTS


# --- alerting on new queue items -------------------------------------------

def _flag(ticker="AAPL", concept="long_term_debt", year=2025, variance=0.136):
    return NewFlag(ticker, concept, year, 78_328_000_000, 90_678_000_000, variance)


def test_single_company_message_links_to_that_company():
    message = format_message([_flag()])
    assert "1 new item for AAPL" in message
    assert "/company/AAPL" in message


def test_multi_company_message_links_to_the_queue():
    message = format_message([_flag("AAPL"), _flag("GOOGL"), _flag("MSFT")])
    assert "3 new items for 3 companies" in message
    assert "/dashboard" in message


def test_message_names_the_numbers_an_analyst_needs():
    message = format_message([_flag()])
    assert "long_term_debt FY2025" in message
    assert "78,328,000,000" in message
    assert "90,678,000,000" in message
    assert "13.6%" in message


def test_worst_variance_is_listed_first():
    message = format_message([
        _flag("AAPL", variance=0.02), _flag("MSFT", variance=0.40),
        _flag("GOOGL", variance=0.15),
    ])
    assert message.index("MSFT") < message.index("GOOGL") < message.index("AAPL")


def test_long_list_is_truncated_rather_than_unreadable():
    message = format_message([_flag(f"T{i}", variance=0.1 + i / 100) for i in range(20)])
    assert "and 12 more" in message
    assert message.count("•") == 8
