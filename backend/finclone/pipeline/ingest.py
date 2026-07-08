"""Ingest a company's full XBRL history from SEC EDGAR into the database.

Usage: python -m finclone.pipeline.ingest AAPL [MSFT ...]
"""

import sys
from datetime import date

from sqlalchemy import select

from finclone.db import get_session, init_db
from finclone.edgar.client import EdgarClient, filing_index_url
from finclone.edgar.documents import accession_document_map, inline_viewer_url
from finclone.models import Company, FinancialFact
from finclone.pipeline.normalize import (
    TAG_INDEX,
    classify_tag,
    is_annual_duration,
    is_quarterly_duration,
)
from finclone.scout_cache import refresh_metrics_cache
from finclone.taxonomy.sic_map import sector_for_sic

_ALLOWED_UNITS = {"USD", "shares", "USD/shares"}


def _fiscal_label(end: date, fye_month: int) -> tuple[int, int]:
    """(fiscal_year, quarter 1-4) for a period ending at `end`, given the
    company's fiscal-year-end month.

    Derived from the period's own dates — NEVER from companyfacts' fy/fp
    fields, which describe the fiscal period of the FILING, so prior-year
    comparatives carry the current filing's labels. Fiscal years are labeled
    by their ending calendar year (Apple FY2016 ends Sep 2016; NVDA FY2024
    ends Jan 2024). Tolerates 52/53-week calendars spilling a few days past
    the month boundary (e.g. a Sep FYE landing on Oct 1).
    """
    month, year = end.month, end.year
    if end.day <= 6:  # 52/53-week spillover into the next month
        month -= 1
        if month == 0:
            month, year = 12, year - 1
    months_after_fye = (month - fye_month) % 12
    quarter = 4 if months_after_fye == 0 else (months_after_fye + 2) // 3
    fiscal_year = year if month <= fye_month else year + 1
    return fiscal_year, quarter


def _period_label(entry: dict, is_flow: bool, fye_month: int) -> tuple[int, str] | None:
    """Classify one companyfacts entry as (fiscal_year, Q1-Q4 | FY), or None.

    Duration facts are classified by actual span length because 6- and
    9-month YTD spans are also present in the data.
    """
    end_str = entry.get("end")
    if not end_str:
        return None
    end = date.fromisoformat(end_str)
    start = entry.get("start")

    if start is None:  # instant (balance-sheet) fact — belongs to a quarter end
        fy, quarter = _fiscal_label(end, fye_month)
        return fy, f"Q{quarter}"

    if is_annual_duration(start, end_str):
        if not is_flow:
            return None
        fy, _ = _fiscal_label(end, fye_month)
        return fy, "FY"
    if is_quarterly_duration(start, end_str):
        fy, quarter = _fiscal_label(end, fye_month)
        return fy, f"Q{quarter}"
    return None  # YTD span or irregular period — skip


def ingest_ticker(ticker: str, client: EdgarClient) -> None:
    cik = client.ticker_to_cik(ticker)
    submissions = client.company_submissions(cik)
    facts_payload = client.company_facts(cik)
    # Audit links point into the filing document itself (inline-XBRL viewer);
    # the index page is the fallback for accessions we can't resolve.
    documents = accession_document_map(client, cik, submissions)

    sic = str(submissions.get("sic") or "") or None
    fye_raw = str(submissions.get("fiscalYearEnd") or "1231")
    fye_month = int(fye_raw[:2]) if fye_raw[:2].isdigit() and 1 <= int(fye_raw[:2]) <= 12 else 12
    with get_session() as session:
        company = session.scalar(select(Company).where(Company.cik == cik))
        if company is None:
            company = Company(cik=cik, ticker=ticker.upper())
            session.add(company)
        company.name = submissions.get("name") or ticker.upper()
        company.sic = sic
        company.sector = sector_for_sic(sic)
        session.flush()

        existing = {
            (f.concept, f.fiscal_year, f.fiscal_period, f.accession_number, f.derived)
            for f in session.scalars(
                select(FinancialFact).where(FinancialFact.company_id == company.id)
            )
        }

        inserted = 0
        gaap_facts = facts_payload.get("facts", {}).get("us-gaap", {})
        for tag, tag_data in gaap_facts.items():
            mapping = classify_tag(tag)
            if mapping is None:
                continue
            canonical, _priority, is_flow = mapping

            for unit, entries in tag_data.get("units", {}).items():
                if unit not in _ALLOWED_UNITS:
                    continue
                for entry in entries:
                    if entry.get("val") is None:
                        continue
                    labeled = _period_label(entry, is_flow, fye_month)
                    if labeled is None:
                        continue
                    fy, period = labeled
                    key = (tag, fy, period, entry["accn"], False)
                    if key in existing:
                        continue
                    existing.add(key)
                    session.add(FinancialFact(
                        company_id=company.id,
                        concept=tag,
                        canonical_concept=canonical,
                        unit=unit,
                        value=float(entry["val"]),
                        fiscal_year=fy,
                        fiscal_period=period,
                        start_date=date.fromisoformat(entry["start"]) if entry.get("start") else None,
                        end_date=date.fromisoformat(entry["end"]),
                        form=entry.get("form", ""),
                        accession_number=entry["accn"],
                        filed_date=date.fromisoformat(entry["filed"]),
                        source_url=(
                            inline_viewer_url(cik, entry["accn"], documents[entry["accn"]])
                            if documents.get(entry["accn"])
                            else filing_index_url(cik, entry["accn"])
                        ),
                    ))
                    inserted += 1

        session.commit()
        derived = derive_q4(company.id)
        refresh_metrics_cache(session, company.id)
        session.commit()
        print(f"{ticker.upper()}: {inserted} facts ingested, {derived} Q4 values derived")


def current_facts(facts: list[FinancialFact]) -> FinancialFact | None:
    """Pick the current value among facts for one (canonical, fy, period):
    best tag priority first, then latest filing."""
    if not facts:
        return None
    return min(
        facts,
        key=lambda f: (TAG_INDEX[f.concept][1] if f.concept in TAG_INDEX else 99,
                       -f.filed_date.toordinal()),
    )


def derive_q4(company_id: int) -> int:
    """Insert Q4 = FY - Q1 - Q2 - Q3 for flow concepts where Q4 wasn't reported."""
    inserted = 0
    with get_session() as session:
        rows = list(session.scalars(
            select(FinancialFact).where(FinancialFact.company_id == company_id)
        ))
        by_period: dict[tuple[str, int, str], list[FinancialFact]] = {}
        has_q4: set[tuple[str, int]] = set()
        for f in rows:
            if f.fiscal_period == "Q4":  # reported or previously derived
                has_q4.add((f.canonical_concept, f.fiscal_year))
            if not f.derived:
                by_period.setdefault(
                    (f.canonical_concept, f.fiscal_year, f.fiscal_period), []
                ).append(f)

        flow_concepts = {name for name, _, flow in TAG_INDEX.values() if flow}

        for (canonical, fy, period), facts in list(by_period.items()):
            if period != "FY" or canonical not in flow_concepts or (canonical, fy) in has_q4:
                continue
            fy_fact = current_facts(facts)
            quarters = [current_facts(by_period.get((canonical, fy, q), []))
                        for q in ("Q1", "Q2", "Q3")]
            if fy_fact is None or any(q is None for q in quarters):
                continue
            session.add(FinancialFact(
                company_id=company_id,
                concept=fy_fact.concept,
                canonical_concept=canonical,
                unit=fy_fact.unit,
                value=fy_fact.value - sum(q.value for q in quarters),
                fiscal_year=fy,
                fiscal_period="Q4",
                start_date=None,
                end_date=fy_fact.end_date,
                form=fy_fact.form,
                accession_number=fy_fact.accession_number,
                filed_date=fy_fact.filed_date,
                source_url=fy_fact.source_url,
                derived=True,
            ))
            has_q4.add((canonical, fy))
            inserted += 1
        session.commit()
    return inserted


def main() -> None:
    tickers = sys.argv[1:]
    if not tickers:
        print("Usage: python -m finclone.pipeline.ingest TICKER [TICKER ...]")
        raise SystemExit(1)
    init_db()
    client = EdgarClient()
    for ticker in tickers:
        ingest_ticker(ticker, client)


if __name__ == "__main__":
    main()
