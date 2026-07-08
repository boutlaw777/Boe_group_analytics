"""Run LLM KPI extraction across the whole database (PDR §3, NLP engine).

Companies in sectors with specific KPI definitions are processed first (they
yield the richest metrics — RevPAR, ARR, NIM...), then everything else (which
still gets the generic KPIs: headcount, backlog, buybacks). Companies that
already have any KPI facts are skipped, so the sweep is safe to stop and
re-run — it resumes where it left off.

Usage:
    python -m finclone.pipeline.kpi_sweep                # full sweep
    python -m finclone.pipeline.kpi_sweep --sectors-only # only covered sectors
    python -m finclone.pipeline.kpi_sweep --limit 100    # stop after 100 companies

Each company costs ~6 DeepSeek calls plus one EDGAR filing download, so the
full sweep is a multi-day background run; --sectors-only is the high-value
first pass.
"""

import argparse

from openai import OpenAI
from sqlalchemy import select

from finclone.config import DEEPSEEK_API_KEY, DEEPSEEK_BASE_URL
from finclone.db import get_session, init_db
from finclone.edgar.client import EdgarClient
from finclone.models import Company, KpiFact
from finclone.pipeline.kpi_extract import extract_ticker
from finclone.taxonomy.kpi_definitions import SECTOR_KPIS


def main() -> None:
    parser = argparse.ArgumentParser(description="KPI-extract every company in the database")
    parser.add_argument("--limit", type=int, default=None,
                        help="stop after this many companies are processed")
    parser.add_argument("--sectors-only", action="store_true",
                        help="only companies in sectors that have specific KPI definitions")
    args = parser.parse_args()

    if not DEEPSEEK_API_KEY:
        raise SystemExit("DEEPSEEK_API_KEY is not set in backend\\.env")

    init_db()
    with get_session() as session:
        done_ids = set(session.scalars(select(KpiFact.company_id).distinct()))
        companies = [
            (c.ticker, c.sector, c.id)
            for c in session.scalars(select(Company).order_by(Company.ticker))
        ]

    covered = [c for c in companies if c[1] in SECTOR_KPIS]
    rest = [] if args.sectors_only else [c for c in companies if c[1] not in SECTOR_KPIS]
    queue = covered + rest

    client = EdgarClient()
    llm = OpenAI(api_key=DEEPSEEK_API_KEY, base_url=DEEPSEEK_BASE_URL)
    print(f"KPI sweep: {len(queue)} companies queued ({len(covered)} in covered sectors), "
          f"{len(done_ids)} already have KPIs and will be skipped")

    processed = 0
    failed = 0
    for ticker, _sector, company_id in queue:
        if args.limit is not None and processed >= args.limit:
            break
        if company_id in done_ids:
            continue
        try:
            extract_ticker(ticker, client, llm)
            processed += 1
        except KeyboardInterrupt:
            print("\nStopped — re-run to resume from here.")
            return
        except (Exception, SystemExit) as e:  # one bad filer must not stop the sweep
            failed += 1
            print(f"  {ticker}: skipped ({type(e).__name__}: {e})")
        if processed and processed % 25 == 0:
            print(f"--- {processed} processed, {failed} skipped ---")

    print(f"KPI sweep done: {processed} companies processed, {failed} skipped. "
          "Re-run any time — companies with KPIs are skipped.")


if __name__ == "__main__":
    main()
