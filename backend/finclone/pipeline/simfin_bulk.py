"""SimFin bulk baseline ingestion (PDR §3: "Backend ingests SimFin bulk data
as a baseline").

Populates the database with standardized annual fundamentals for the full
SimFin US universe (~6,600 companies) so every company has a working model
immediately. Baseline rows are provenance-marked (form="SimFin", accession
"simfin-baseline") and always lose to SEC-extracted facts in current-value
selection — unknown concepts rank below every mapped XBRL tag in
`current_facts` — so running the EDGAR ingest for a ticker upgrades it in
place with filing-level audit links.

SimFin's v3 API has no CSV file downloads (the v2 bulk endpoint is gone);
bulk ingestion batches the statements/compact endpoint at the plan's
2-companies-per-call limit and is resumable: companies that already have
facts (SEC or baseline) are skipped, so re-running after an interruption or
a daily API cap continues where it left off.

Usage:
    python -m finclone.pipeline.simfin_bulk               # full universe
    python -m finclone.pipeline.simfin_bulk --limit 50    # first 50 (smoke test)
    python -m finclone.pipeline.simfin_bulk --quarterly   # include Q1-Q3 flows
    python -m finclone.pipeline.simfin_bulk AAPL TSLA     # specific tickers only
"""

import sys
import time
from datetime import date

import httpx
from sqlalchemy import insert, select

from finclone.config import SIMFIN_API_KEY
from finclone.db import get_session, init_db
from finclone.models import Company, FinancialFact
from finclone.scout_cache import refresh_metrics_cache

_SIMFIN_BASE = "https://backend.simfin.com/api/v3"
_BATCH = 2  # companies per statements call (plan limit)
_ACCESSION = "simfin-baseline"
_CALL_PAUSE = 0.6  # polite gap between calls — bursts trip SimFin's throttling
_MAX_CONSECUTIVE_FAILURES = 5  # circuit breaker: stop instead of hammering

# SimFin statement -> {exact SimFin column: (canonical concept, is_flow)}
_FIELD_MAP: dict[str, dict[str, tuple[str, bool]]] = {
    "PL": {
        "Revenue": ("revenue", True),
        "Cost of revenue": ("cost_of_revenue", True),
        "Gross Profit": ("gross_profit", True),
        "Selling, General & Administrative": ("sga_expense", True),
        "Research & Development": ("research_development", True),
        "Operating Income (Loss)": ("operating_income", True),
        "Net Income": ("net_income", True),
    },
    "CF": {
        "Cash from Operating Activities": ("operating_cash_flow", True),
        "Change in Fixed Assets & Intangibles": ("capex", True),
        "Stock-Based Compensation": ("stock_based_compensation", True),
    },
    "BS": {  # instants — SimFin reports these on quarter ends only
        "Cash & Cash Equivalents": ("cash_and_equivalents", False),
        "Total Assets": ("total_assets", False),
        "Total Liabilities": ("total_liabilities", False),
        "Total Equity": ("stockholders_equity", False),
        "Long Term Debt": ("long_term_debt", False),
    },
    "DERIVED": {
        "Earnings Per Share, Diluted": ("eps_diluted", True),
    },
}

# SimFin sector names -> our taxonomy where a clean match exists; anything
# unmapped keeps SimFin's own name (Company.sector is free text).
_SECTOR_MAP = {
    "Banks": "Banking",
    "Biotechnology": "Pharmaceuticals & Biotech",
    "Drug Manufacturers": "Pharmaceuticals & Biotech",
    "Application Software": "Software & SaaS",
    "Online Media": "Media & Entertainment",
    "Entertainment": "Media & Entertainment",
    "Computer Hardware": "Computer Hardware",
    "Semiconductors": "Semiconductors",
    "Communication Equipment": "Electronics & Semiconductors",
    "Asset Management": "Capital Markets",
    "Brokers, Exchanges & Other": "Capital Markets",
    "Metals & Mining": "Mining",
    "Oil & Gas - E&P": "Oil & Gas",
    "Consumer Packaged Goods": "Food & Beverage",
    "Restaurants": "Hospitality",
    "Travel & Leisure": "Hospitality",
    "Medical Devices": "Healthcare Services",
    "Medical Diagnostics & Research": "Healthcare Services",
    "Engineering & Construction": "Construction",
    "Chemicals": "Chemicals",
    "REITs": "REITs",
}


def _adjusted(end: date) -> tuple[int, int]:
    """(month, year) with the ingest pipeline's 52/53-week spillover rule."""
    month, year = end.month, end.year
    if end.day <= 6:
        month -= 1
        if month == 0:
            month, year = 12, year - 1
    return month, year


def _fy_label(end: date) -> int:
    """Fiscal year labeled by its (spillover-adjusted) ending calendar year —
    the company's own convention, matching the EDGAR ingest."""
    _, year = _adjusted(end)
    return year


def _quarter_fy_label(end: date, quarter: int) -> int:
    """Fiscal-year label for a quarter: the calendar year the fiscal year ends
    in, projected from the quarter end (Q1 ends 9 months before FYE)."""
    month, year = _adjusted(end)
    month += (4 - quarter) * 3
    return year + (month - 1) // 12


def _fetch_json(http: httpx.Client, path: str, params: dict) -> object:
    """GET with retry/backoff for rate limits and transient errors."""
    for attempt in range(4):
        try:
            resp = http.get(f"{_SIMFIN_BASE}{path}", params=params,
                            headers={"Authorization": f"api-key {SIMFIN_API_KEY}",
                                     "accept": "application/json"})
        except httpx.HTTPError:
            time.sleep(3 * (attempt + 1))
            continue
        if resp.status_code == 429:
            time.sleep(10 * (attempt + 1))
            continue
        if resp.status_code >= 500:
            time.sleep(2 ** attempt)
            continue
        resp.raise_for_status()
        return resp.json()
    raise RuntimeError(f"SimFin: giving up on {path} after retries")


def _sec_ticker_map() -> dict[str, tuple[str, str]]:
    """SEC's official ticker -> (10-digit CIK, registrant name) mapping."""
    resp = httpx.get(
        "https://www.sec.gov/files/company_tickers.json",
        headers={"User-Agent": "FinClone/0.1 (mohsin@boegroup.com)"},
        timeout=60,
    )
    resp.raise_for_status()
    return {
        row["ticker"].upper(): (str(row["cik_str"]).zfill(10), row["title"])
        for row in resp.json().values()
    }


_GENERIC_TOKENS = {
    "inc", "corp", "corporation", "incorporated", "company", "co", "ltd",
    "limited", "plc", "group", "holdings", "holding", "the", "trust", "lp",
    "sa", "nv", "ag", "se", "llc", "and", "of",
}


def _names_agree(simfin_name: str, sec_name: str) -> bool:
    """True when the two names share at least one distinctive token.

    SimFin's universe includes delisted companies whose tickers the SEC has
    since reassigned (e.g. 'P' was Pandora Media); matching those against the
    current SEC registrant would attribute data to the wrong company."""
    def tokens(name: str) -> set[str]:
        cleaned = "".join(ch if ch.isalnum() else " " for ch in name.lower())
        return {t for t in cleaned.split() if t not in _GENERIC_TOKENS}
    a, b = tokens(simfin_name), tokens(sec_name)
    return bool(a & b) or not a or not b


def _facts_from_statements(statements: list[dict], company_id: int, cik: str,
                           quarterly: bool) -> list[dict]:
    """Flatten one company's SimFin statement blocks into FinancialFact rows.

    Annual baseline: FY rows for flows, Q4 rows for balance-sheet instants
    (the web app and Data Sheets read year-end instants from Q4). With
    quarterly=True, Q1-Q3 are kept as well.
    """
    source_url = f"https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&CIK={cik}"
    best: dict[tuple[str, int, str], dict] = {}
    for stmt in statements:
        field_map = _FIELD_MAP.get(stmt.get("statement", ""))
        if not field_map:
            continue
        columns = stmt.get("columns", [])
        col_idx = {c: i for i, c in enumerate(columns)}
        date_idx = col_idx.get("Report Date")
        period_idx = col_idx.get("Fiscal Period")
        publish_idx = col_idx.get("Publish Date")
        if date_idx is None or period_idx is None:
            continue
        for row in stmt.get("data", []):
            try:
                end = date.fromisoformat(str(row[date_idx]))
            except (TypeError, ValueError):
                continue
            period = str(row[period_idx])
            if period == "FY":
                fy, label = _fy_label(end), "FY"
            elif period in ("Q1", "Q2", "Q3", "Q4"):
                quarter = int(period[1])
                fy, label = _quarter_fy_label(end, quarter), period
            else:
                continue

            filed = end
            if publish_idx is not None and row[publish_idx]:
                try:
                    filed = date.fromisoformat(str(row[publish_idx]))
                except (TypeError, ValueError):
                    pass

            for column, (canonical, is_flow) in field_map.items():
                i = col_idx.get(column)
                if i is None or i >= len(row):
                    continue
                value = row[i]
                if not isinstance(value, (int, float)):
                    continue
                if is_flow and label != "FY" and not quarterly:
                    continue  # annual baseline: flows from FY rows only
                if not is_flow and label == "Q4":
                    pass  # year-end instant — always kept
                elif not is_flow and not quarterly:
                    continue
                key = (canonical, fy, label)
                existing = best.get(key)
                if existing is not None and existing["filed_date"] >= filed:
                    continue
                best[key] = {
                    "company_id": company_id,
                    "concept": f"SimFin:{column}"[:255],
                    "canonical_concept": canonical,
                    "unit": "USD/shares" if canonical == "eps_diluted" else "USD",
                    "value": float(value),
                    "fiscal_year": fy,
                    "fiscal_period": label,
                    "start_date": None,
                    "end_date": end,
                    "form": "SimFin",
                    "accession_number": _ACCESSION,
                    "filed_date": filed,
                    "source_url": source_url,
                    "derived": False,
                }
    return list(best.values())


def run_bulk(only_tickers: set[str] | None = None, limit: int | None = None,
             quarterly: bool = False) -> None:
    init_db()
    with httpx.Client(timeout=60.0) as http:
        universe = _fetch_json(http, "/companies/list", {})
        sec_map = _sec_ticker_map()

        candidates = []
        seen_ciks: set[str] = set()
        name_mismatches = 0
        for entry in universe:
            ticker = (entry.get("ticker") or "").upper()
            if not ticker or ticker not in sec_map:
                continue  # not on SEC EDGAR (foreign/OTC) — can't audit later
            if only_tickers and ticker not in only_tickers:
                continue
            cik, sec_name = sec_map[ticker]
            if not _names_agree(entry.get("name") or "", sec_name):
                name_mismatches += 1  # likely a delisted company's recycled ticker
                continue
            if cik in seen_ciks:
                continue  # second share class of a company we already have
            seen_ciks.add(cik)
            candidates.append((ticker, cik, entry))

        with get_session() as session:
            have_facts = set(session.scalars(
                select(Company.ticker).join(
                    FinancialFact, FinancialFact.company_id == Company.id
                ).distinct()
            ))
            existing_ciks = {cik: cid for cik, cid in session.execute(
                select(Company.cik, Company.id))}

        todo = [c for c in candidates if c[0] not in have_facts]
        if limit:
            todo = todo[:limit]
        print(f"SimFin universe: {len(universe)} | on EDGAR: {len(candidates)} "
              f"| name mismatches skipped: {name_mismatches} "
              f"| already ingested: {len(candidates) - len(todo) if not limit else '-'} "
              f"| to do: {len(todo)}", flush=True)

        done = failed = total_facts = consecutive_failures = 0
        periods = "FY,Q1,Q2,Q3,Q4" if quarterly else "FY,Q4"
        for i in range(0, len(todo), _BATCH):
            batch = todo[i:i + _BATCH]
            tickers = ",".join(t for t, _, _ in batch)
            time.sleep(_CALL_PAUSE)
            try:
                payload = _fetch_json(http, "/companies/statements/compact", {
                    "ticker": tickers,
                    "statements": "PL,BS,CF,DERIVED",
                    "period": periods,
                })
                consecutive_failures = 0
            except Exception as exc:  # keep going; run is resumable
                print(f"  batch {tickers} failed: {exc}", flush=True)
                failed += len(batch)
                consecutive_failures += 1
                if consecutive_failures >= _MAX_CONSECUTIVE_FAILURES:
                    print(f"Aborting after {consecutive_failures} consecutive "
                          f"failures — SimFin is throttling or unreachable. "
                          f"Re-run later; the run resumes where it left off. "
                          f"({done} done so far)", flush=True)
                    return
                continue
            by_ticker = {(c.get("ticker") or "").upper(): c for c in payload}

            with get_session() as session:
                touched: list[int] = []
                for ticker, cik, entry in batch:
                    company_payload = by_ticker.get(ticker)
                    if not company_payload:
                        failed += 1
                        continue
                    rows = _facts_from_statements(
                        company_payload.get("statements", []), 0, cik, quarterly)
                    if not rows:
                        failed += 1  # delisted / no data on this plan — no shell row
                        continue
                    company_id = existing_ciks.get(cik)
                    if company_id is None:
                        raw_sector = entry.get("sectorName")
                        sector = _SECTOR_MAP.get(raw_sector) or raw_sector
                        company = Company(
                            cik=cik,
                            ticker=ticker,
                            name=(entry.get("name") or sec_map[ticker][1])[:255],
                            sic=None,
                            sector=sector[:64] if sector else None,
                        )
                        session.add(company)
                        session.flush()
                        company_id = company.id
                        existing_ciks[cik] = company_id
                    for row in rows:
                        row["company_id"] = company_id
                    session.execute(insert(FinancialFact), rows)
                    total_facts += len(rows)
                    touched.append(company_id)
                    done += 1
                session.commit()
                for company_id in touched:
                    refresh_metrics_cache(session, company_id)
                session.commit()

            if done and done % 100 < _BATCH:
                print(f"  {done}/{len(todo)} companies, {total_facts} facts, "
                      f"{failed} failed", flush=True)

        print(f"Done: {done} companies ingested, {total_facts} baseline facts, "
              f"{failed} failed/skipped", flush=True)


def main() -> None:
    args = [a for a in sys.argv[1:]]
    limit = None
    quarterly = False
    tickers: set[str] = set()
    i = 0
    while i < len(args):
        if args[i] == "--limit":
            limit = int(args[i + 1])
            i += 2
        elif args[i] == "--quarterly":
            quarterly = True
            i += 1
        else:
            tickers.add(args[i].upper())
            i += 1
    if not SIMFIN_API_KEY:
        raise SystemExit("SIMFIN_API_KEY is not set in backend\\.env")
    run_bulk(only_tickers=tickers or None, limit=limit, quarterly=quarterly)


if __name__ == "__main__":
    main()
