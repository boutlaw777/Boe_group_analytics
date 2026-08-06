"""Valuation Auditing agent: the deterministic freshness check and its tools.

There is no valuation/DCF engine in this repo — this audits the platform's
own computed screening metrics (finclone.scout.compute_metrics) against
themselves and against the company's GICS industry profile, not against a
third-party source (that's Statement Reconciliation's job).
"""

import json
from datetime import date

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from finclone.agents.tools import (
    VALUATION_SEVERITIES, industry_profile_tool, record_finding_tool, screen_metrics_tool,
)
from finclone.agents.valuation_agent import _metrics_match, check_cache_freshness
from finclone.db import Base
from finclone.models import Company, FinancialFact, ScreenMetrics, ValuationAuditFinding


@pytest.fixture()
def session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with sessionmaker(bind=engine)() as s:
        yield s


@pytest.fixture()
def company(session):
    c = Company(cik="0000000001", ticker="TEST", name="Test Co", sic="7372",
               sector="Software & SaaS")
    session.add(c)
    session.commit()
    return c


def _fact(company_id, concept, value, fy, fp="FY"):
    return FinancialFact(
        company_id=company_id, concept=f"us-gaap:{concept}", canonical_concept=concept,
        unit="USD", value=value, fiscal_year=fy, fiscal_period=fp, start_date=None,
        end_date=date(fy, 12, 31), form="10-K", accession_number=f"0001-{fy}",
        filed_date=date(fy + 1, 2, 1), source_url=f"https://sec.gov/{fy}",
    )


# --- _metrics_match: the tolerance is for JSON round-trip, not real drift ---

def test_identical_dicts_match():
    m = {"fiscal_year": 2024, "revenue": 1000.0, "net_margin": 0.2}
    assert _metrics_match(m, dict(m))


def test_tiny_float_noise_still_matches():
    """JSON round-trip through metrics_json must not produce false positives."""
    a = {"fiscal_year": 2024, "net_margin": 0.2 + 1e-12}
    b = {"fiscal_year": 2024, "net_margin": 0.2}
    assert _metrics_match(a, b)


def test_real_difference_does_not_match():
    a = {"fiscal_year": 2024, "revenue": 1000.0}
    b = {"fiscal_year": 2024, "revenue": 1200.0}
    assert not _metrics_match(a, b)


def test_key_present_in_one_but_not_other_does_not_match():
    assert not _metrics_match({"fiscal_year": 2024, "roe": 0.1}, {"fiscal_year": 2024})


def test_different_fiscal_year_does_not_match():
    assert not _metrics_match({"fiscal_year": 2023}, {"fiscal_year": 2024})


# --- check_cache_freshness: detects, actually repairs, and records ----------

def test_no_finding_when_nothing_cached_and_nothing_computable(session, company):
    assert check_cache_freshness(session, company) is None
    assert session.scalar(select(ValuationAuditFinding)) is None


def test_no_finding_when_cache_matches_a_fresh_recompute(session, company):
    session.add(_fact(company.id, "revenue", 1000.0, 2024))
    session.commit()
    # Seed the cache with exactly what compute_metrics would produce, via the
    # session-agnostic write path — not scout_cache.refresh_metrics_cache,
    # which recomputes by opening its own connection to the globally
    # configured engine rather than reading through this test's session.
    from finclone.agents.valuation_agent import _annual_values
    from finclone.scout import compute_metrics
    from finclone.scout_cache import _store
    _store(session, company.id, compute_metrics(_annual_values(session, company.id)), None)
    session.commit()

    assert check_cache_freshness(session, company) is None
    assert session.scalar(select(ValuationAuditFinding)) is None


def test_stale_cache_is_detected_and_actually_repaired(session, company):
    """An audit that notices staleness and leaves it stale is worse than
    fixing it — the cache must reflect current facts afterward, not just get
    a finding logged about it."""
    session.add(_fact(company.id, "revenue", 1000.0, 2024))
    session.commit()
    # A stale cache: written before this year's revenue was ingested.
    session.add(ScreenMetrics(company_id=company.id, fiscal_year=2023,
                             metrics_json=json.dumps({"fiscal_year": 2023, "revenue": 500.0}),
                             updated=date(2024, 1, 1)))
    session.commit()

    finding = check_cache_freshness(session, company)

    assert finding is not None
    assert finding.concern == "cache_stale"
    assert finding.severity == "note"  # auto-repaired, not something a human must act on

    refreshed = session.get(ScreenMetrics, company.id)
    assert refreshed.fiscal_year == 2024
    assert json.loads(refreshed.metrics_json)["revenue"] == 1000.0


def test_missing_cache_with_computable_metrics_is_flagged(session, company):
    """Recomputable but never cached at all — the ingest path should have
    written a cache row and didn't."""
    session.add(_fact(company.id, "revenue", 1000.0, 2024))
    session.commit()

    finding = check_cache_freshness(session, company)
    assert finding is not None
    assert session.get(ScreenMetrics, company.id) is not None  # now backfilled


# --- new tools ---------------------------------------------------------------

def test_screen_metrics_tool_returns_cached_metrics(session, company):
    session.add(ScreenMetrics(company_id=company.id, fiscal_year=2024,
                             metrics_json=json.dumps({"fiscal_year": 2024, "net_margin": 0.3}),
                             updated=date.today()))
    session.commit()
    result = screen_metrics_tool(session, company).fn()
    assert result["fiscal_year"] == 2024
    assert result["metrics"]["net_margin"] == 0.3


def test_screen_metrics_tool_errors_cleanly_when_absent(session, company):
    result = screen_metrics_tool(session, company).fn()
    assert "error" in result


def test_industry_profile_tool_resolves_from_sic():
    company = Company(cik="0000000002", ticker="SOFT", name="Soft Co", sic="7372", sector=None)
    result = industry_profile_tool(company).fn()
    assert result["gics_industry"] == "Software"
    assert "key_kpis" in result and result["key_kpis"]


def test_industry_profile_tool_errors_when_unresolvable():
    company = Company(cik="0000000003", ticker="UNK", name="Unknown Co", sic=None, sector=None)
    result = industry_profile_tool(company).fn()
    assert "error" in result


def test_record_finding_stores_a_valid_finding(session, company):
    tool = record_finding_tool(session, company, 2024)
    result = tool.fn(concern="margin_implausible", severity="concern",
                     reason="Operating margin of 340% is not plausible for this industry.")
    assert result["status"] == "recorded"
    row = session.get(ValuationAuditFinding, result["id"])
    assert row.concern == "margin_implausible"
    assert row.fiscal_year == 2024


def test_record_finding_rejects_unknown_severity(session, company):
    tool = record_finding_tool(session, company, 2024)
    result = tool.fn(concern="x", severity="critical", reason="y")
    assert "error" in result
    assert session.scalar(select(ValuationAuditFinding)) is None


def test_record_finding_rejects_empty_reason(session, company):
    tool = record_finding_tool(session, company, 2024)
    result = tool.fn(concern="x", severity="note", reason="   ")
    assert "error" in result


def test_record_finding_rejects_empty_concern(session, company):
    tool = record_finding_tool(session, company, 2024)
    result = tool.fn(concern="  ", severity="note", reason="y")
    assert "error" in result


def test_valuation_severities_are_exactly_two():
    """Deliberately binary — note vs concern — not a third tier nothing else
    in the queue has."""
    assert VALUATION_SEVERITIES == ("note", "concern")
