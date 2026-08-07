"""Valuation Auditing agent (BOE Analytics M2, worker role 3).

There is no DCF/valuation engine in this repo (that lives in the separate
fable-dcf codebase), so this is scoped around what BOE Analytics actually
computes: finclone.scout.compute_metrics (margins, growth, ROE, FCF margin,
cached per company in ScreenMetrics) and the niche KPIs Data Parsing extracts.
The job is auditing those derived numbers for internal consistency and
industry-appropriate plausibility — not fabricating a valuation we don't have.

Two layers, same cheap-and-certain-first shape as flag_triage's rules/model
split:

  1. check_cache_freshness — deterministic, free, no LLM. Recomputes metrics
     from the current stored facts and compares against the cached
     ScreenMetrics row. A mismatch means the cache is stale (an ingest ran
     since it was last refreshed) — arithmetic, not judgement, so it never
     needs the agent.

  2. The agent — reviews the computed metrics and KPI facts against the
     company's GICS industry profile (expected valuation method, expected
     KPIs) for plausibility, and cross-checks KPI facts against financial
     facts for consistency (e.g. a SaaS company's reported ARR should track
     its reported revenue) — checks neither Data Parsing nor Statement
     Reconciliation perform, since Reconciliation only compares against SimFin
     and Parsing only extracts once without judging the result.

Usage: python -m finclone.agents.valuation_agent AAPL [MSFT ...]
       (requires KPI_API_KEY in .env, and the ticker already ingested)
"""

import argparse
import math
from datetime import date

from openai import OpenAI
from sqlalchemy import select

from finclone.agents.runtime import AgentResult, run_agent, start_run
from finclone.agents.tools import (
    existing_kpis_tool, fetch_excerpt_tool, industry_profile_tool,
    our_fact_tool, record_finding_tool, screen_metrics_tool,
)
from finclone.config import (
    KPI_API_KEY, KPI_BASE_URL, KPI_MODEL, require_bulk_provider)
from finclone.db import get_session, init_db
from finclone.edgar.client import EdgarClient
from finclone.edgar.documents import fetch_filing_text, latest_filing
from finclone.models import Company, FinancialFact, ScreenMetrics, ValuationAuditFinding
from finclone.pipeline.crossref import _annual_facts_from_rows
from finclone.pipeline.kpi_extract import _NotIngested
from finclone.scout import compute_metrics
from finclone.taxonomy.gics_bridge import industry_for_company


def _annual_values(session, company_id: int) -> dict[tuple[str, int], float]:
    """Same contract as crossref._our_annual_values, but reads through the
    caller's own session rather than opening a separate one against the
    globally-configured engine. crossref._our_annual_values is right for
    pipeline scripts that own no session of their own; here it would silently
    read through a different connection than the one this module was handed
    (and, not incidentally, made check_cache_freshness untestable against an
    in-memory database — this surfaced exactly that way, as a test failure
    trying to reach the real production database)."""
    rows = list(session.scalars(select(FinancialFact).where(FinancialFact.company_id == company_id)))
    return {key: f.value for key, f in _annual_facts_from_rows(rows).items()}

_SYSTEM = """You are the Valuation Auditing agent for a financial data platform. You review a \
company's own computed metrics — margins, growth, ROE, free cash flow — and its extracted niche \
KPIs, for internal consistency and industry-appropriate plausibility. You are not checking these \
numbers against an external source (a different agent already does that); you are checking \
whether the platform's OWN numbers hold together and make sense for this company's industry.

Call get_screen_metrics for the computed metrics, get_industry_profile for the expected \
valuation approach and typical KPIs for this GICS industry, and get_existing_kpis for what's been \
extracted. Use get_our_fact if you need a specific raw figure, and fetch_filing_excerpt if a \
metric looks anomalous and a one-off item (an impairment, a divestiture, a restatement) might \
explain it before you flag it as a concern.

Look for things like:
- A margin or ROE outside a plausible range for this industry, or a sharp swing you can't explain.
- The industry's typical valuation method (e.g. DCF) sitting awkwardly against this company's own \
numbers (e.g. persistently negative free cash flow makes a pure DCF hard to apply as-is).
- A KPI figure inconsistent with the financial facts it should roughly track (e.g. reported ARR \
far outside what reported revenue would suggest) — this may mean one of the two extractions is \
wrong.

Call record_finding only for something specific and grounded in the actual numbers — never for \
routine variation, a single ordinary bad quarter, or a vague hunch. Most companies you review will \
warrant zero findings; that is the expected, healthy outcome, not a failure to find something. \
When you are done, reply with a short plain-text summary and no further tool calls."""

# Two metrics computed from the exact same deterministic formula should match
# exactly when nothing changed; this tolerance only absorbs float round-trip
# through JSON storage (metrics_json), not real drift — a genuinely stale
# cache differs by much more than this once new facts have actually landed.
_FRESHNESS_REL_TOL = 1e-9
_FRESHNESS_ABS_TOL = 1e-6


def _metrics_match(cached: dict, recomputed: dict) -> bool:
    keys = set(cached) | set(recomputed)
    for key in keys:
        a, b = cached.get(key), recomputed.get(key)
        if (a is None) != (b is None):
            return False
        if a is None:
            continue
        if not math.isclose(a, b, rel_tol=_FRESHNESS_REL_TOL, abs_tol=_FRESHNESS_ABS_TOL):
            return False
    return True


def check_cache_freshness(session, company: Company) -> ValuationAuditFinding | None:
    """Deterministic pre-check: does the cached ScreenMetrics row match what
    compute_metrics produces from the company's current stored facts?

    If not, this actually refreshes the cache (not just reports the problem —
    an audit that notices a stale cache and leaves it stale is a worse outcome
    than either fixing it or staying silent) and records what it found. Returns
    None when there's nothing to flag: either they already match, or there's
    nothing cached and nothing computable.
    """
    import json as _json

    from finclone.scout_cache import _store as _store_screen_metrics

    recomputed = compute_metrics(_annual_values(session, company.id))
    cached_row = session.get(ScreenMetrics, company.id)
    cached = _json.loads(cached_row.metrics_json) if cached_row and cached_row.metrics_json else None

    if recomputed is None and cached is None:
        return None
    if (recomputed is None) != (cached is None):
        stale = True
    else:
        stale = not _metrics_match(cached, recomputed)
    if not stale:
        return None

    fiscal_year = (recomputed or cached).get("fiscal_year", 0)
    # Not scout_cache.refresh_metrics_cache: that recomputes by opening its own
    # session against the globally-configured engine, same issue this function
    # itself just avoided by taking _annual_values(session, ...) as a parameter.
    # _store is the session-agnostic write-only half of that module.
    _store_screen_metrics(session, company.id, recomputed, cached_row)
    finding = ValuationAuditFinding(
        company_id=company.id, fiscal_year=int(fiscal_year), concern="cache_stale",
        severity="note",
        reason=("Cached screening metrics no longer matched a fresh recompute from stored "
               "facts (likely a new filing was ingested since it last refreshed) — the "
               "cache has been refreshed as part of this audit."),
        created=date.today(),
    )
    session.add(finding)
    session.commit()
    return finding


def run_valuation_agent(ticker: str, max_steps: int = 8) -> AgentResult | None:
    """Runs the freshness pre-check, then the audit agent, for one company.

    Returns None if the company has no computable metrics at all (nothing to
    audit) — not an error.
    """
    client = EdgarClient()
    cik = client.ticker_to_cik(ticker)
    with get_session() as session:
        company = session.scalar(select(Company).where(Company.cik == cik))
        if company is None:
            raise _NotIngested(ticker.upper())

        stale_finding = check_cache_freshness(session, company)
        recomputed = compute_metrics(_annual_values(session, company.id))
        if recomputed is None:
            return None
        fiscal_year = int(recomputed["fiscal_year"])

        submissions = client.company_submissions(cik)
        filing = latest_filing(submissions)
        text = fetch_filing_text(client, cik, filing)

        industry = industry_for_company(company.sic, company.sector)
        goal = (
            f"Audit {company.ticker} ({industry.gics_industry if industry else 'unmapped sector'}) "
            f"FY{fiscal_year} valuation inputs for internal consistency and industry-appropriate "
            "plausibility."
        )
        if stale_finding is not None:
            goal += (" Note: the metrics cache was stale and has just been refreshed — the "
                    "figures you're given now are current.")

        run = start_run(session, role="valuation", company_id=company.id, goal=goal)
        tools = [
            screen_metrics_tool(session, company),
            industry_profile_tool(company),
            existing_kpis_tool(session, company),
            our_fact_tool(session, company),
            fetch_excerpt_tool(text),
            record_finding_tool(session, company, fiscal_year),
        ]
        llm = OpenAI(api_key=KPI_API_KEY, base_url=KPI_BASE_URL, timeout=60, max_retries=1)
        return run_agent(llm, KPI_MODEL, _SYSTEM, goal, tools,
                         session=session, run=run, max_steps=max_steps)


def main() -> None:
    parser = argparse.ArgumentParser(description="Agentic Valuation Auditing")
    parser.add_argument("tickers", nargs="+", help="tickers to audit (already ingested)")
    parser.add_argument("--max-steps", type=int, default=8)
    args = parser.parse_args()
    require_bulk_provider()
    print(f"Valuation Auditing agent | provider: {KPI_BASE_URL} | model: {KPI_MODEL}")
    init_db()

    for ticker in args.tickers:
        try:
            result = run_valuation_agent(ticker.upper(), max_steps=args.max_steps)
            if result is None:
                print(f"{ticker.upper()}: no computable metrics — nothing to audit")
                continue
            print(f"{ticker.upper()}: {result.status} in {result.steps} tool calls")
            print(f"  {result.outcome}")
        except _NotIngested as e:
            print(f"{e}: not ingested — run: python -m finclone.pipeline.ingest {e}")
        except Exception as e:
            print(f"{ticker.upper()}: agent run failed ({type(e).__name__}: {str(e)[:160]})")


if __name__ == "__main__":
    main()
