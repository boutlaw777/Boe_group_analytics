"""Bulk-ingest the SEC-listed universe (PDR: broad coverage).

Walks the SEC's official ticker list (roughly largest companies first),
skipping companies that already have SEC-extracted facts — companies with
only SimFin baseline data DO get processed (this run is what upgrades them
to deep, audit-linked SEC data). Safe to stop and re-run — it resumes where
it left off. Respects the EDGAR rate limit via EdgarClient.

Usage:
    python -m finclone.pipeline.bulk_ingest --limit 100     # top ~100 companies
    python -m finclone.pipeline.bulk_ingest                 # the full universe
    python -m finclone.pipeline.bulk_ingest --db-only       # upgrade only companies
                                                            # already in the database

Expect roughly 20-40 companies per minute (dominated by EDGAR download time),
so ~100 companies is a few minutes and the full universe is an overnight run.
KPI extraction is intentionally separate (it costs LLM tokens per company):
    python -m finclone.pipeline.kpi_extract TICKER
"""

import argparse
import time

from sqlalchemy import select

from finclone.db import get_session, init_db
from finclone.models import Company, FinancialFact
from finclone.edgar.client import EdgarClient
from finclone.pipeline.ingest import ingest_ticker

_BASELINE_ACCESSION = "simfin-baseline"


def main() -> None:
    parser = argparse.ArgumentParser(description="Bulk-ingest the SEC universe")
    parser.add_argument("--limit", type=int, default=None,
                        help="stop after this many companies are in the database")
    parser.add_argument("--db-only", action="store_true",
                        help="only companies already in the database (upgrades their "
                             "baseline data to SEC facts; adds no new tickers)")
    args = parser.parse_args()

    init_db()
    client = EdgarClient()

    universe = client.get_json("https://www.sec.gov/files/company_tickers.json")
    entries = list(universe.values())
    with get_session() as session:
        # "Done" = has SEC-extracted facts. Baseline-only companies are NOT
        # done — running this is what upgrades them to SEC data.
        sec_ids = set(session.scalars(
            select(FinancialFact.company_id)
            .where(FinancialFact.accession_number != _BASELINE_ACCESSION)
            .distinct()
        ))
        companies = list(session.scalars(select(Company)))
        have = {c.ticker for c in companies if c.id in sec_ids}
        if args.db_only:
            db_tickers = {c.ticker for c in companies}
            entries = [e for e in entries if e["ticker"] in db_tickers]

    target = args.limit or len(entries)
    done = len(have)
    failed = 0
    started = time.monotonic()
    print(f"Universe: {len(entries)} listed entities | already SEC-extracted: {done} | target: {target}")

    for entry in entries:
        if done >= target:
            break
        ticker = entry["ticker"]
        if ticker in have or "-" in ticker or "." in ticker:  # skip units/warrants/dual-class oddities
            continue
        try:
            ingest_ticker(ticker, client)
            done += 1
            have.add(ticker)
        except KeyboardInterrupt:
            print("\nStopped — re-run to resume from here.")
            return
        except Exception as e:  # one bad filer must not stop the sweep
            failed += 1
            print(f"  {ticker}: skipped ({type(e).__name__}: {e})")
        if done and done % 25 == 0:
            rate = done / max(1.0, (time.monotonic() - started) / 60)
            print(f"--- {done}/{target} in database ({failed} skipped, ~{rate:.0f}/min this run) ---")

    print(f"Done: {done} companies in database, {failed} skipped. "
          "Re-run any time — already-ingested companies are skipped instantly.")


if __name__ == "__main__":
    main()
