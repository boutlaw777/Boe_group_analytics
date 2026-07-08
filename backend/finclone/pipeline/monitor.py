"""EDGAR filing monitor (PDR §3): poll for new 10-K/10-Q/8-K filings and
refresh the database when they appear.

Single pass (for Windows Task Scheduler / cron):
    python -m finclone.pipeline.monitor

Continuous watch mode (poll every N minutes):
    python -m finclone.pipeline.monitor --watch 10

Monitors every company already in the database. Ingestion is idempotent, so
re-processing is safe.
"""

import argparse
import time
from datetime import date

from sqlalchemy import select

from finclone.db import get_session, init_db
from finclone.edgar.client import EdgarClient
from finclone.models import Company, SeenFiling
from finclone.pipeline.ingest import ingest_ticker

_WATCHED_FORMS = ("10-K", "10-Q", "8-K")
# Forms that carry XBRL financial data worth re-ingesting. 8-Ks are recorded
# (audit trail / future NLP triggers) but don't force a full re-ingest.
_INGEST_FORMS = ("10-K", "10-Q")


def _recent_filings(submissions: dict) -> list[dict]:
    recent = submissions.get("filings", {}).get("recent", {})
    return [
        {
            "form": recent["form"][i],
            "accession_number": recent["accessionNumber"][i],
            "filed_date": recent["filingDate"][i],
        }
        for i in range(len(recent.get("form", [])))
        if recent["form"][i] in _WATCHED_FORMS
    ]


def check_company(company_id: int, client: EdgarClient) -> int:
    """Check one company for unseen filings; re-ingest if any carry financials.
    Returns the number of new filings found."""
    with get_session() as session:
        company = session.get(Company, company_id)
        seen = {
            s.accession_number
            for s in session.scalars(
                select(SeenFiling).where(SeenFiling.company_id == company_id)
            )
        }

    submissions = client.company_submissions(company.cik)
    new_filings = [f for f in _recent_filings(submissions) if f["accession_number"] not in seen]
    if not new_filings:
        return 0

    for f in new_filings:
        print(f"  {company.ticker}: new {f['form']} filed {f['filed_date']}")

    if any(f["form"] in _INGEST_FORMS for f in new_filings):
        ingest_ticker(company.ticker, client)

    with get_session() as session:
        for f in new_filings:
            session.add(SeenFiling(
                company_id=company_id,
                accession_number=f["accession_number"],
                form=f["form"],
                filed_date=date.fromisoformat(f["filed_date"]),
            ))
        session.commit()
    return len(new_filings)


def run_once(client: EdgarClient) -> None:
    with get_session() as session:
        companies = [(c.id, c.ticker) for c in session.scalars(select(Company))]
    if not companies:
        print("No companies in the database yet — ingest one first "
              "(python -m finclone.pipeline.ingest AAPL)")
        return
    total = 0
    for company_id, ticker in companies:
        try:
            total += check_company(company_id, client)
        except Exception as e:  # one bad company must not stop the sweep
            print(f"  {ticker}: check failed ({e})")
    print(f"Monitor pass complete: {len(companies)} companies checked, {total} new filings")


def main() -> None:
    parser = argparse.ArgumentParser(description="Monitor EDGAR for new filings")
    parser.add_argument("--watch", type=int, metavar="MINUTES",
                        help="poll continuously every N minutes instead of one pass")
    args = parser.parse_args()

    init_db()
    client = EdgarClient()

    if args.watch:
        print(f"Watching EDGAR (every {args.watch} min) — Ctrl+C to stop")
        while True:
            run_once(client)
            time.sleep(args.watch * 60)
    else:
        run_once(client)


if __name__ == "__main__":
    main()
