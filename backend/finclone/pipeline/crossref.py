"""Cross-reference validation against SimFin (PDR §3).

SimFin provides an independent baseline for our SEC-extracted numbers.
Annual values that differ by more than the variance threshold (default 1%)
are flagged for human review.

Values are compared as absolute magnitudes — sign conventions differ between
sources (e.g. SimFin reports capex-like outflows as negative cash flows;
XBRL's PaymentsToAcquirePropertyPlantAndEquipment is positive).

Usage:
    python -m finclone.pipeline.crossref AAPL [MSFT ...]   # specific tickers
    python -m finclone.pipeline.crossref --all             # every company with
                                                           # SEC-extracted facts
    python -m finclone.pipeline.crossref --all --limit 50  # first 50 of those

--all skips baseline-only companies: their facts ARE SimFin data, so the
comparison would always trivially match while spending an API call each.
"""

import argparse
import time

import httpx
from sqlalchemy import delete, select

from finclone.config import CROSSREF_VARIANCE_THRESHOLD, SIMFIN_API_KEY
from finclone.db import get_session, init_db
from finclone.models import Company, FinancialFact, ValidationFlag
from finclone.pipeline.ingest import current_facts

_SIMFIN_BASE = "https://backend.simfin.com/api/v3"

# SimFin indexes some companies under a different share class than we track
# (Alphabet is GOOG on SimFin; we ingest the Class A ticker GOOGL).
_SIMFIN_TICKER_ALIASES = {"GOOGL": "GOOG"}

# SimFin statement code -> {SimFin column name: canonical concept}
# Column names follow SimFin's standardized (bulk/compact) layout.
_SIMFIN_FIELD_MAP: dict[str, dict[str, str]] = {
    "PL": {
        "Revenue": "revenue",
        "Cost of revenue": "cost_of_revenue",
        "Gross Profit": "gross_profit",
        "Research & Development": "research_development",
        "Operating Income (Loss)": "operating_income",
        "Net Income": "net_income",
        # Per-share values are deliberately excluded: SimFin restates them for
        # stock splits while we store as-reported values, so comparing them
        # floods the review queue with known-convention noise.
    },
    "BS": {
        # "Cash, Cash Equivalents & Short Term Investments" is deliberately
        # excluded: SimFin folds short-term investments into it, while our
        # cash_and_equivalents is cash only — a known-convention mismatch.
        "Total Assets": "total_assets",
        "Total Liabilities": "total_liabilities",
        "Total Equity": "stockholders_equity",
        "Long Term Debt": "long_term_debt",
    },
    "CF": {
        "Cash from Operating Activities": "operating_cash_flow",
        "Change in Fixed Assets & Intangibles": "capex",
    },
}


def variance(ours: float, reference: float) -> float:
    """Relative difference of absolute magnitudes; sign conventions differ
    between sources. Returns 0 when both are 0."""
    if reference == 0:
        return 0.0 if ours == 0 else float("inf")
    return abs(abs(ours) - abs(reference)) / abs(reference)


def _parse_statement(columns: list[str], data: list[list], field_map: dict[str, str],
                     reference: dict[tuple[str, int], float]) -> None:
    """Fold one SimFin compact statement block into the reference dict.

    Keyed by the calendar year of the period end ("Report Date"), not SimFin's
    "Fiscal Year" label — SimFin labels January-ending years one behind the
    company's own convention (NVDA's year ending 2020-01-31 is SimFin FY2019
    but NVIDIA/XBRL fiscal 2020)."""
    try:
        date_idx = columns.index("Report Date")
    except ValueError:
        return
    col_idx = {col: i for i, col in enumerate(columns)}
    for row in data:
        try:
            end_year = int(str(row[date_idx])[:4])
        except (TypeError, ValueError):
            continue
        for column, concept in field_map.items():
            i = col_idx.get(column)
            if i is None or i >= len(row):
                continue
            value = row[i]
            if isinstance(value, (int, float)) and value != 0:
                reference[(concept, end_year)] = float(value)


def fetch_reference_values(ticker: str) -> dict[tuple[str, int], float]:
    """SimFin annual values keyed by (canonical_concept, fiscal_year)."""
    reference: dict[tuple[str, int], float] = {}
    simfin_ticker = _SIMFIN_TICKER_ALIASES.get(ticker.upper(), ticker.upper())
    with httpx.Client(timeout=30.0) as http:
        resp = http.get(
            f"{_SIMFIN_BASE}/companies/statements/compact",
            params={"ticker": simfin_ticker, "statements": "PL,BS,CF", "period": "FY"},
            headers={"Authorization": f"api-key {SIMFIN_API_KEY}",
                     "accept": "application/json"},
        )
        resp.raise_for_status()
        payload = resp.json()
    if isinstance(payload, dict):  # SimFin returns a dict on errors
        raise RuntimeError(f"SimFin error: {payload.get('message', payload)}")
    for company in payload:
        for stmt in company.get("statements", []):
            field_map = _SIMFIN_FIELD_MAP.get(stmt.get("statement", ""))
            if field_map:
                _parse_statement(stmt.get("columns", []), stmt.get("data", []),
                                 field_map, reference)
    return reference


def _our_annual_facts(company_id: int) -> dict[tuple[str, int], FinancialFact]:
    """Our current annual facts keyed by (concept, fiscal-year label)."""
    with get_session() as session:
        rows = list(session.scalars(
            select(FinancialFact).where(FinancialFact.company_id == company_id)
        ))
    return _annual_facts_from_rows(rows)


def _annual_facts_from_rows(rows: list[FinancialFact]) -> dict[tuple[str, int], FinancialFact]:
    """Same selection as _our_annual_facts, on already-fetched fact rows —
    lets bulk callers (scout_cache) fetch many companies in one query."""
    grouped: dict[tuple[str, int, str], list[FinancialFact]] = {}
    for f in rows:
        grouped.setdefault((f.canonical_concept, f.fiscal_year, f.fiscal_period), []).append(f)

    # Annual comparison: FY durations for flows; Q4 instants (year-end) for
    # balance-sheet concepts that have no FY entry.
    ours: dict[tuple[str, int], FinancialFact] = {}
    for (concept, fy, period), facts in grouped.items():
        if period == "Q4" and (concept, fy, "FY") not in grouped:
            fact = current_facts(facts)
            if fact is not None:
                ours[(concept, fy)] = fact
    for (concept, fy, period), facts in grouped.items():
        if period == "FY":
            fact = current_facts(facts)
            if fact is not None:
                ours[(concept, fy)] = fact
    return ours


def _our_annual_values(company_id: int) -> dict[tuple[str, int], float]:
    """Annual values keyed by (concept, fiscal-year label). Used by Scout."""
    return {key: f.value for key, f in _our_annual_facts(company_id).items()}


def crossref_ticker(ticker: str) -> None:
    with get_session() as session:
        company = session.scalar(select(Company).where(Company.ticker == ticker.upper()))
    if company is None:
        print(f"{ticker.upper()}: not ingested — skipping")
        return

    reference = fetch_reference_values(ticker)
    # Align on the period end's calendar year — SimFin's fiscal-year labels
    # run one behind the company's own for January-ending years (NVDA).
    ours = {(concept, f.end_date.year): (fy, f.value)
            for (concept, fy), f in _our_annual_facts(company.id).items()}
    shared = sorted(set(reference) & set(ours))
    if not shared:
        print(f"{ticker.upper()}: no overlapping values to compare")
        return

    flags: list[tuple[str, int, float, float, float]] = []
    for key in shared:
        fy_label, our_value = ours[key]
        v = variance(our_value, reference[key])
        if v > CROSSREF_VARIANCE_THRESHOLD:
            flags.append((key[0], fy_label, our_value, reference[key], v))

    with get_session() as session:
        # Refresh this company's flags wholesale — a re-run reflects current
        # state. Executed immediately (not queued on the session) because the
        # ORM flushes pending INSERTs before DELETEs, which would collide with
        # the old rows on the unique constraint.
        session.execute(delete(ValidationFlag).where(ValidationFlag.company_id == company.id))
        for concept, fy, our_value, ref_value, v in flags:
            session.add(ValidationFlag(
                company_id=company.id, canonical_concept=concept, fiscal_year=fy,
                our_value=our_value, reference_value=ref_value, variance=v,
            ))
        session.commit()

    matched = len(shared) - len(flags)
    print(f"{ticker.upper()}: {len(shared)} values compared, "
          f"{matched} within {CROSSREF_VARIANCE_THRESHOLD:.0%}, {len(flags)} flagged")
    for concept, fy, our_value, ref_value, v in sorted(flags, key=lambda x: -x[4]):
        print(f"  FLAG {concept} FY{fy}: ours={our_value:,.0f} ref={ref_value:,.0f} ({v:.1%} variance)")


def main() -> None:
    parser = argparse.ArgumentParser(description="Cross-reference our values against SimFin")
    parser.add_argument("tickers", nargs="*", help="tickers to cross-reference")
    parser.add_argument("--all", action="store_true",
                        help="sweep every company with SEC-extracted facts")
    parser.add_argument("--limit", type=int, default=None,
                        help="with --all: stop after this many companies")
    args = parser.parse_args()
    if not args.tickers and not args.all:
        parser.error("pass tickers or --all")
    if not SIMFIN_API_KEY:
        raise SystemExit("SIMFIN_API_KEY is not set in backend\\.env")
    init_db()

    tickers = [t.upper() for t in args.tickers]
    if args.all:
        with get_session() as session:
            sec_ids = set(session.scalars(
                select(FinancialFact.company_id)
                .where(FinancialFact.accession_number != "simfin-baseline")
                .distinct()
            ))
            tickers += [c.ticker
                        for c in session.scalars(select(Company).order_by(Company.ticker))
                        if c.id in sec_ids and c.ticker not in tickers]
        if args.limit:
            tickers = tickers[:args.limit]
        print(f"Cross-referencing {len(tickers)} companies with SEC-extracted facts...")

    failed = 0
    for i, ticker in enumerate(tickers, start=1):
        for attempt in range(3):
            try:
                crossref_ticker(ticker)
                break
            except KeyboardInterrupt:
                print(f"\nStopped at {ticker} ({i - 1}/{len(tickers)} done) — "
                      "re-running refreshes each company's flags wholesale, so a "
                      "restart is safe.")
                return
            except httpx.TransportError as e:  # flaky DNS/connect — retry
                if attempt == 2:
                    failed += 1
                    print(f"{ticker}: crossref failed after 3 tries ({e})")
                else:
                    time.sleep(2 * (attempt + 1))
            except Exception as e:  # one SimFin miss must not stop the sweep
                failed += 1
                print(f"{ticker}: crossref failed ({type(e).__name__}: {str(e)[:120]})")
                break
        if args.all:
            time.sleep(0.5)  # SimFin free-tier rate limit (~2 req/s)
            if i % 25 == 0:
                print(f"--- {i}/{len(tickers)} ({failed} failed) ---")
    if args.all:
        print(f"Done: {len(tickers)} companies cross-referenced, {failed} failed.")


if __name__ == "__main__":
    main()
