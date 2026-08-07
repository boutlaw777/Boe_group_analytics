"""Data Parsing agent (BOE Analytics M2, worker role 1).

kpi_extract.py runs a fixed, deterministic sweep: pre-score every filing chunk
once, hand each to the model, keep what comes back. That's the right shape for
a several-thousand-company nightly sweep — cheap and predictable — but the
model never chooses what to look at next or decides when it's done, which is
what makes something an *agent* rather than a script.

This module is the agentic counterpart for targeted use: one company at a
time, called directly or via a Statement Reconciliation handoff
(finclone.agents.reconciliation_agent). The model chooses its own search
keywords, reads filing excerpts on demand through fetch_filing_excerpt, and
records what it verifies through record_kpi — stopping on its own judgement
instead of after a fixed chunk budget. Every tool call is logged to
AgentRun/AgentStep (finclone.agents.runtime) as the execution log.

The deterministic sweep in kpi_extract.py is still what you want for bulk
coverage; this is for one company you want examined more thoroughly, or a
follow-up after a Reconciliation flag.

Usage: python -m finclone.agents.parsing_agent AAPL [MSFT ...]
       (requires KPI_API_KEY in .env, and the ticker already ingested)
"""

import argparse

from openai import OpenAI
from sqlalchemy import select

from finclone.agents.runtime import AgentResult, run_agent, start_run
from finclone.agents.tools import existing_kpis_tool, fetch_excerpt_tool, record_kpi_tool
from finclone.config import (
    KPI_API_KEY, KPI_BASE_URL, KPI_MODEL, require_bulk_provider)
from finclone.db import get_session, init_db
from finclone.edgar.client import EdgarClient
from finclone.edgar.documents import fetch_filing_text, inline_viewer_url, latest_filing
from finclone.models import Company
from finclone.pipeline.kpi_extract import _NotIngested
from finclone.taxonomy.gics_bridge import industry_for_company
from finclone.taxonomy.kpi_definitions import kpis_for_company

_SYSTEM = """You are the Data Parsing agent for a financial data platform. Your job is to find \
and record niche KPIs (sector-specific metrics XBRL doesn't carry, e.g. RevPAR, ARR, wafer \
capacity) from a company's SEC filing.

Rules:
- Only record values that appear explicitly in text you fetched with fetch_filing_excerpt. Never \
estimate, compute, or recall a value from outside that text.
- Call get_existing_kpis first so you don't redo work already stored.
- Call fetch_filing_excerpt with the keywords most likely to find each target KPI; if a search \
comes back empty or irrelevant, try different or broader keywords before giving up on that KPI.
- Call record_kpi once per distinct (KPI, period) pair you can verify, with the verbatim quote \
that contains the value. If the filing gives the same KPI for multiple periods (e.g. current and \
prior year), record each period separately.
- Normalize the period field to "Q<n> FY<yyyy>", "H1 FY<yyyy>", "FY<yyyy>", or "as of <yyyy-mm-dd>".
- When you have covered the target KPIs — or additional searches stop finding anything new — stop \
by replying with a short plain-text summary and no further tool calls. Don't call \
fetch_filing_excerpt more than a few times per KPI."""


def run_parsing_agent(ticker: str, goal: str | None = None, max_steps: int = 8) -> AgentResult:
    client = EdgarClient()
    cik = client.ticker_to_cik(ticker)
    with get_session() as session:
        company = session.scalar(select(Company).where(Company.cik == cik))
        if company is None:
            raise _NotIngested(ticker.upper())

        submissions = client.company_submissions(cik)
        filing = latest_filing(submissions)
        text = fetch_filing_text(client, cik, filing)
        source_url = inline_viewer_url(cik, filing["accession_number"], filing["primary_document"])

        industry = industry_for_company(company.sic, company.sector)
        labels = [k["label"] for k in kpis_for_company(company.sic, company.sector)]
        default_goal = (
            f"Target KPIs for {company.ticker} "
            f"({industry.gics_industry if industry else 'unmapped sector'}) in its "
            f"{filing['form']} filed {filing['filed_date']}: " + "; ".join(labels))
        goal = goal or default_goal

        run = start_run(session, role="parsing", company_id=company.id, goal=goal)
        tools = [
            fetch_excerpt_tool(text),
            existing_kpis_tool(session, company),
            record_kpi_tool(session, company, filing, source_url),
        ]
        llm = OpenAI(api_key=KPI_API_KEY, base_url=KPI_BASE_URL, timeout=60, max_retries=1)
        return run_agent(llm, KPI_MODEL, _SYSTEM, goal, tools,
                         session=session, run=run, max_steps=max_steps)


def main() -> None:
    parser = argparse.ArgumentParser(description="Agentic Data Parsing — targeted KPI extraction")
    parser.add_argument("tickers", nargs="+", help="tickers to run (already ingested)")
    parser.add_argument("--max-steps", type=int, default=8)
    args = parser.parse_args()
    require_bulk_provider()
    print(f"Data Parsing agent | provider: {KPI_BASE_URL} | model: {KPI_MODEL}")
    init_db()

    for ticker in args.tickers:
        try:
            result = run_parsing_agent(ticker.upper(), max_steps=args.max_steps)
            print(f"{ticker.upper()}: {result.status} in {result.steps} tool calls")
            print(f"  {result.outcome}")
        except _NotIngested as e:
            print(f"{e}: not ingested — run: python -m finclone.pipeline.ingest {e}")
        except Exception as e:
            print(f"{ticker.upper()}: agent run failed ({type(e).__name__}: {str(e)[:160]})")


if __name__ == "__main__":
    main()
