"""Statement Reconciliation agent (BOE Analytics M2, worker role 2).

flag_triage.run_llm (stage 2) sends the model one fixed, pre-selected batch of
filing excerpts per company and asks for a verdict on every open flag in one
shot. This module gives the same job to an agent instead: it chooses its own
search keywords per flag (seeded with the filing vocabulary stage 2 learned
the hard way — see flag_triage._CONCEPT_KEYWORDS, born from AAPL's 10-Q
saying "Term debt" where a plain "long-term debt" search scored zero), looks
up our own stored value and its provenance on demand, and can hand off to the
Data Parsing agent (finclone.agents.parsing_agent) when a definitional
disclosure might explain a gap better than reasoning from the numbers alone —
a real cross-agent consultation, not a bigger prompt.

Verdicts use the same vocabulary and close-only-if-filing-grounded rule as
flag_triage (LLM_RESOLUTIONS, NEEDS_REVIEW, BASES); resolved_by is 'agent' /
'agent-inferred' rather than 'model' / 'model-inferred' so the two triage
paths stay distinguishable in the queue.

Usage: python -m finclone.agents.reconciliation_agent AAPL [MSFT ...]
       (requires KPI_API_KEY in .env; run stage 1 --rules first — see
       finclone.pipeline.flag_triage — so the agent only sees what arithmetic
       couldn't already settle for free)
"""

import argparse

from openai import OpenAI
from sqlalchemy import select

from finclone.agents.runtime import AgentResult, run_agent, start_run
from finclone.agents.tools import (
    consult_parsing_agent_tool, fetch_excerpt_tool, our_fact_tool, record_verdict_tool,
)
from finclone.config import (
    TRIAGE_API_KEY, TRIAGE_BASE_URL, TRIAGE_MODEL, require_triage_provider)
from finclone.db import get_session, init_db
from finclone.edgar.client import EdgarClient
from finclone.edgar.documents import fetch_filing_text, latest_filing
from finclone.models import Company, ValidationFlag
from finclone.pipeline.flag_triage import _CONCEPT_KEYWORDS

_SYSTEM = """You are the Statement Reconciliation agent for a financial data platform. For each \
open flag, our SEC-extracted value disagrees with an independent reference source (SimFin) by \
more than 1%. Decide WHY, so a human only reviews what genuinely needs review.

Resolutions: convention (sign or definitional difference — the underlying figure agrees), \
immaterial (rounding or scale), restatement (the company later revised the figure), real_issue \
(likely a genuine extraction error), unexplained (you cannot determine the cause).

For every flag, call get_our_fact to see our stored value and which filing it came from, and \
fetch_filing_excerpt with keywords for that concept (hints are given with each flag) if you need \
to read the actual disclosure. If a definition or reconciling-items footnote might explain a gap \
better than you can find yourself, call consult_parsing_agent instead of guessing.

Call record_verdict for every flag you were given, exactly once each. basis must be 'filing_text' \
only when you actually read the relevant figures or disclosure in a fetched excerpt or a \
consult_parsing_agent answer — otherwise 'reasoning'. You are given ONE filing, usually the most \
recent; many flags concern earlier fiscal years whose figures are NOT in it — for those, basis is \
'reasoning' or the resolution is 'unexplained'. Do not hedge inside a confident verdict: if your \
reason would contain "cannot verify" or "likely", either the basis is 'reasoning' or the \
resolution is 'unexplained'. Never guess a verdict to fill the field — an honest 'unexplained' \
routes it to a person; a wrong 'convention' hides a real error. Once every flag has a recorded \
verdict, reply with a short plain-text summary and no further tool calls."""


def _goal_for(ticker: str, filing: dict, flags: list[ValidationFlag]) -> str:
    lines = [
        f"Company: {ticker}",
        f"Filing available to you: {filing['form']} filed {filing['filed_date']} "
        f"(this is the only filing text available to you)",
        "",
        "Open flags (values are in reported currency units):",
    ]
    for f in flags:
        hints = ", ".join(_CONCEPT_KEYWORDS.get(
            f.canonical_concept, (f.canonical_concept.replace("_", " "),))[:4])
        lines.append(
            f"- id={f.id} concept={f.canonical_concept} fiscal_year={f.fiscal_year} "
            f"ours={f.our_value:+,.0f} reference={f.reference_value:+,.0f} "
            f"magnitude_gap={abs(f.variance):.1%} (try keywords like: {hints})"
        )
    return "\n".join(lines)


def run_reconciliation_agent(ticker: str, max_steps: int = 16) -> AgentResult | None:
    """Runs the agent over one company's untriaged flags.

    Returns None if there are none — not an error, just nothing to do.
    """
    with get_session() as session:
        company = session.scalar(select(Company).where(Company.ticker == ticker.upper()))
        if company is None:
            raise ValueError(f"{ticker.upper()} is not ingested")
        flags = list(session.scalars(
            select(ValidationFlag)
            .where(ValidationFlag.company_id == company.id, ValidationFlag.resolution.is_(None))
            .order_by(ValidationFlag.canonical_concept, ValidationFlag.fiscal_year)
        ))
        if not flags:
            return None

        client = EdgarClient()
        filing = latest_filing(client.company_submissions(company.cik))
        text = fetch_filing_text(client, company.cik, filing)
        goal = _goal_for(company.ticker, filing, flags)

        run = start_run(session, role="reconciliation", company_id=company.id, goal=goal)
        llm = OpenAI(api_key=TRIAGE_API_KEY, base_url=TRIAGE_BASE_URL, timeout=90, max_retries=1)
        tools = [
            fetch_excerpt_tool(text),
            our_fact_tool(session, company),
            record_verdict_tool(session, {f.id for f in flags}),
            consult_parsing_agent_tool(llm, TRIAGE_MODEL, session, run, company, filing, text),
        ]
        return run_agent(llm, TRIAGE_MODEL, _SYSTEM, goal, tools,
                         session=session, run=run, max_steps=max_steps)


def main() -> None:
    parser = argparse.ArgumentParser(description="Agentic Statement Reconciliation")
    parser.add_argument("tickers", nargs="+", help="tickers with open flags to triage")
    parser.add_argument("--max-steps", type=int, default=16)
    args = parser.parse_args()
    require_triage_provider()
    print(f"Statement Reconciliation agent | provider: {TRIAGE_BASE_URL} | model: {TRIAGE_MODEL}")
    init_db()

    for ticker in args.tickers:
        try:
            result = run_reconciliation_agent(ticker.upper(), max_steps=args.max_steps)
            if result is None:
                print(f"{ticker.upper()}: no open flags")
                continue
            print(f"{ticker.upper()}: {result.status} in {result.steps} tool calls")
            print(f"  {result.outcome}")
        except Exception as e:
            print(f"{ticker.upper()}: agent run failed ({type(e).__name__}: {str(e)[:160]})")


if __name__ == "__main__":
    main()
