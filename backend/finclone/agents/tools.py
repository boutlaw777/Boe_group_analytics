"""Tools shared by the agent roles (BOE Analytics M2).

Each factory closes over the context a tool needs (a session, a company, the
filing text already fetched for this run) and returns a runtime.Tool the
model can call. Validation logic is imported from the pipeline modules it
must agree with — record_kpi reuses kpi_extract's _clean_kpi, record_verdict
reuses flag_triage's resolution vocabulary — rather than redefined here, so
the agentic and deterministic paths can never silently diverge on what counts
as a valid record.
"""

import json
from datetime import date

from sqlalchemy import select

from finclone.agents.runtime import Tool, run_agent, start_run
from finclone.models import FinancialFact, KpiFact, ValidationFlag, ValuationAuditFinding
from finclone.pipeline.crossref import _annual_facts_from_rows
from finclone.pipeline.flag_triage import BASES, LLM_RESOLUTIONS, NEEDS_REVIEW
from finclone.pipeline.kpi_extract import _clean_kpi
from finclone.taxonomy.gics_bridge import industry_for_company

#: Severities the Valuation Auditing agent may record. Deliberately just two —
#: "note" for a mild observation, "concern" for something worth a human's
#: attention — mirroring the binary resolved/needs-review distinction used
#: elsewhere rather than inventing a third tier nothing else in the queue has.
VALUATION_SEVERITIES = ("note", "concern")

_CHUNK_SIZE = 15_000  # characters, matching kpi_extract/flag_triage
_CHUNK_OVERLAP = 500
_MAX_CHUNKS_ALLOWED = 5


def _score_chunks(text: str, keywords: list[str], max_chunks: int) -> list[str]:
    lowered = [k.lower() for k in keywords if str(k).strip()]
    if not lowered:
        return []
    step = _CHUNK_SIZE - _CHUNK_OVERLAP
    scored: list[tuple[int, str]] = []
    for start in range(0, len(text), step):
        chunk = text[start:start + _CHUNK_SIZE]
        low = chunk.lower()
        score = sum(low.count(k) for k in lowered)
        if score:
            scored.append((score, chunk))
    scored.sort(key=lambda pair: -pair[0])
    return [c for _, c in scored[:max_chunks]]


def fetch_excerpt_tool(text: str) -> Tool:
    def _fn(keywords: list, max_chunks: int = 3) -> dict:
        if not isinstance(keywords, list) or not keywords:
            return {"error": "keywords must be a non-empty list of search terms"}
        chunks = _score_chunks(text, [str(k) for k in keywords],
                               max(1, min(int(max_chunks), _MAX_CHUNKS_ALLOWED)))
        if not chunks:
            return {"chunks": [],
                    "note": "no filing text matched these keywords — try broader or different terms"}
        return {"chunks": chunks}

    return Tool(
        name="fetch_filing_excerpt",
        description=("Search the filing for the sections most relevant to the given keywords and "
                    "return up to max_chunks excerpts (~15,000 characters each), highest "
                    "keyword-density first. Call again with different keywords if the first "
                    "search doesn't find what you need."),
        parameters={
            "type": "object",
            "properties": {
                "keywords": {"type": "array", "items": {"type": "string"},
                            "description": "Words or phrases likely to appear near what you're looking for"},
                "max_chunks": {"type": "integer", "description": f"1-{_MAX_CHUNKS_ALLOWED}, default 3"},
            },
            "required": ["keywords"],
        },
        fn=_fn,
    )


def existing_kpis_tool(session, company) -> Tool:
    def _fn() -> dict:
        rows = session.scalars(select(KpiFact).where(KpiFact.company_id == company.id))
        return {"kpis": [{"name": r.name, "period": r.period, "value_text": r.value_text} for r in rows]}

    return Tool(
        name="get_existing_kpis",
        description="List KPIs already recorded for this company, so you don't redo work.",
        parameters={"type": "object", "properties": {}},
        fn=_fn,
    )


def record_kpi_tool(session, company, filing: dict, source_url: str) -> Tool:
    def _fn(name: str, value_text: str, unit: str, period: str, quote: str, value=None) -> dict:
        cleaned = _clean_kpi({"name": name, "value": value, "value_text": value_text,
                              "unit": unit, "period": period, "quote": quote})
        if cleaned is None:
            return {"error": "invalid record — name, value_text, period, and a verbatim quote are all required"}
        existing = session.scalar(select(KpiFact).where(
            KpiFact.company_id == company.id,
            KpiFact.name == cleaned["name"][:128],
            KpiFact.period == cleaned["period"][:64],
            KpiFact.accession_number == filing["accession_number"]))
        if existing is not None:
            return {"status": "already recorded", "id": existing.id}
        row = KpiFact(
            company_id=company.id, name=cleaned["name"][:128], value=cleaned["value"],
            value_text=cleaned["value_text"][:128], unit=cleaned["unit"][:64],
            period=cleaned["period"][:64], source_quote=cleaned["quote"][:1024],
            form=filing["form"], accession_number=filing["accession_number"],
            filed_date=date.fromisoformat(filing["filed_date"]), source_url=source_url,
        )
        session.add(row)
        session.commit()
        return {"status": "recorded", "id": row.id}

    return Tool(
        name="record_kpi",
        description=("Store one verified KPI value with its verbatim source quote. Only call this "
                    "for values that actually appear in text you fetched — never estimate."),
        parameters={
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "canonical KPI name"},
                "value": {"type": ["number", "null"], "description": "normalized to base units"},
                "value_text": {"type": "string", "description": "value as written, e.g. '$1.2 billion'"},
                "unit": {"type": "string", "description": "e.g. USD, rooms, percent, employees"},
                "period": {"type": "string",
                          "description": "e.g. 'Q3 FY2025', 'FY2025', 'as of 2025-06-30'"},
                "quote": {"type": "string", "description": "verbatim sentence containing the value"},
            },
            "required": ["name", "value_text", "unit", "period", "quote"],
        },
        fn=_fn,
    )


def our_fact_tool(session, company) -> Tool:
    def _fn(concept: str, fiscal_year: int) -> dict:
        rows = list(session.scalars(select(FinancialFact).where(
            FinancialFact.company_id == company.id, FinancialFact.canonical_concept == concept)))
        fact = _annual_facts_from_rows(rows).get((concept, int(fiscal_year)))
        if fact is None:
            return {"error": f"no stored annual value for {concept} FY{fiscal_year}"}
        return {"concept": concept, "fiscal_year": fiscal_year, "value": fact.value,
                "form": fact.form, "filed_date": fact.filed_date.isoformat(),
                "source_url": fact.source_url}

    return Tool(
        name="get_our_fact",
        description=("Look up the value we have stored for one of our own concepts/fiscal years, "
                    "with which filing it came from."),
        parameters={
            "type": "object",
            "properties": {
                "concept": {"type": "string"},
                "fiscal_year": {"type": "integer"},
            },
            "required": ["concept", "fiscal_year"],
        },
        fn=_fn,
    )


def record_verdict_tool(session, valid_ids: set[int]) -> Tool:
    def _fn(flag_id: int, resolution: str, basis: str, reason: str) -> dict:
        if flag_id not in valid_ids:
            return {"error": f"flag_id {flag_id} is not one of the flags in this batch"}
        resolution = (resolution or "").strip().lower()
        if resolution not in LLM_RESOLUTIONS:
            return {"error": f"resolution must be one of {list(LLM_RESOLUTIONS)}"}
        basis = (basis or "").strip().lower()
        if basis not in BASES:
            # Never defaults to filing_text: a malformed basis must not be able
            # to close a flag (mirrors flag_triage._clean_verdicts).
            basis = "reasoning"
        reason = (reason or "").strip()
        if not reason:
            return {"error": "reason is required"}
        flag = session.get(ValidationFlag, flag_id)
        if flag is None:
            return {"error": f"flag {flag_id} not found"}
        flag.resolution = resolution
        flag.reason = reason[:512]
        verified = basis == "filing_text"
        # 'agent' / 'agent-inferred' rather than flag_triage's 'model' /
        # 'model-inferred', so the two triage paths stay distinguishable.
        flag.resolved_by = "agent" if verified else "agent-inferred"
        flag.resolved = verified and resolution not in NEEDS_REVIEW
        session.commit()
        return {"status": "recorded", "flag_id": flag_id, "resolved": flag.resolved}

    return Tool(
        name="record_verdict",
        description=("Record your verdict for one flag. basis must be 'filing_text' only if you "
                    "actually read the relevant figures or disclosure in a fetched excerpt — "
                    "otherwise 'reasoning'. A flag only closes when the verdict is benign AND "
                    "grounded in the filing text."),
        parameters={
            "type": "object",
            "properties": {
                "flag_id": {"type": "integer"},
                "resolution": {"type": "string", "enum": list(LLM_RESOLUTIONS)},
                "basis": {"type": "string", "enum": list(BASES)},
                "reason": {"type": "string"},
            },
            "required": ["flag_id", "resolution", "basis", "reason"],
        },
        fn=_fn,
    )


# --- Valuation Auditing tools ----------------------------------------------

def screen_metrics_tool(session, company) -> Tool:
    def _fn() -> dict:
        from finclone.models import ScreenMetrics
        row = session.get(ScreenMetrics, company.id)
        if row is None or not row.metrics_json:
            return {"error": "no computed screening metrics for this company"}
        metrics = json.loads(row.metrics_json)
        return {"fiscal_year": row.fiscal_year, "metrics": metrics}

    return Tool(
        name="get_screen_metrics",
        description=("The platform's own computed valuation-relevant metrics for this company's "
                    "latest fiscal year: margins, growth, ROE, free cash flow. These are what "
                    "you are auditing."),
        parameters={"type": "object", "properties": {}},
        fn=_fn,
    )


def industry_profile_tool(company) -> Tool:
    def _fn() -> dict:
        industry = industry_for_company(company.sic, company.sector)
        if industry is None:
            return {"error": "no GICS industry resolved for this company's SIC/sector"}
        return {
            "gics_industry": industry.gics_industry,
            "primary_valuation": list(industry.primary_valuation),
            "key_kpis": list(industry.key_kpis),
            "complexity": industry.complexity,
        }

    return Tool(
        name="get_industry_profile",
        description=("This company's GICS industry, the valuation methods typically used for it "
                    "(e.g. DCF, EV/EBITDA), and the KPIs analysts expect for that industry — "
                    "context for what 'plausible' looks like here."),
        parameters={"type": "object", "properties": {}},
        fn=_fn,
    )


def record_finding_tool(session, company, fiscal_year: int) -> Tool:
    def _fn(concern: str, severity: str, reason: str) -> dict:
        concern = (concern or "").strip().lower()[:32]
        severity = (severity or "").strip().lower()
        reason = (reason or "").strip()
        if not concern:
            return {"error": "concern is required"}
        if severity not in VALUATION_SEVERITIES:
            return {"error": f"severity must be one of {list(VALUATION_SEVERITIES)}"}
        if not reason:
            return {"error": "reason is required"}
        row = ValuationAuditFinding(
            company_id=company.id, fiscal_year=fiscal_year, concern=concern,
            severity=severity, reason=reason[:512], created=date.today(),
        )
        session.add(row)
        session.commit()
        return {"status": "recorded", "id": row.id}

    return Tool(
        name="record_finding",
        description=("Record one thing worth noting about this company's valuation inputs. Only "
                    "call this for a genuine inconsistency or implausibility you can point to "
                    "specific numbers for — not routine variation. Skip companies with nothing "
                    "worth flagging; you don't have to call this at all."),
        parameters={
            "type": "object",
            "properties": {
                "concern": {"type": "string",
                           "description": "short label, e.g. margin_implausible, "
                                         "kpi_mismatch, fcf_valuation_fit"},
                "severity": {"type": "string", "enum": list(VALUATION_SEVERITIES)},
                "reason": {"type": "string",
                          "description": "specific, cites the actual numbers, one or two sentences"},
            },
            "required": ["concern", "severity", "reason"],
        },
        fn=_fn,
    )


_CONSULT_SYSTEM = """You are the Data Parsing agent, consulted by the Statement Reconciliation \
agent to search a filing for something it couldn't resolve on its own — usually a definitional \
disclosure or reconciling-items footnote. Use fetch_filing_excerpt with keywords you choose; try \
more than one search if the first doesn't find it. Reply with a short plain-text answer: quote the \
relevant sentence if you found one, or say plainly that the filing doesn't address it. Never guess."""


def consult_parsing_agent_tool(llm, model: str, session, parent_run, company, filing: dict,
                               text: str) -> Tool:
    """The cross-agent handoff: Reconciliation delegates a search question to a
    nested Data Parsing run over the same filing, logged under parent_run_id
    so the consultation is traceable, not just a bigger prompt."""

    def _fn(question: str) -> dict:
        question = (question or "").strip()
        if not question:
            return {"error": "question is required"}
        sub_run = start_run(session, role="parsing-consult", company_id=company.id,
                            goal=question, parent_run_id=parent_run.id)
        result = run_agent(llm, model, _CONSULT_SYSTEM, question, [fetch_excerpt_tool(text)],
                           session=session, run=sub_run, max_steps=4)
        return {"answer": result.outcome}

    return Tool(
        name="consult_parsing_agent",
        description=("Hand off a targeted search question to the Data Parsing agent — e.g. 'does "
                    "this filing explain why long-term debt differs from the reference source?' "
                    "Use this instead of guessing when a disclosure might explain a gap."),
        parameters={
            "type": "object",
            "properties": {"question": {"type": "string"}},
            "required": ["question"],
        },
        fn=_fn,
    )
