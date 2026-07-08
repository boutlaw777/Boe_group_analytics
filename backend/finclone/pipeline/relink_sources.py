"""Upgrade audit links on already-ingested facts to filing-document depth.

Facts ingested before the inline-XBRL viewer links pointed at the filing's
EDGAR index page. This re-resolves every SEC accession to its primary
document and rewrites source_url to the SEC inline-XBRL viewer on that
document — the deepest stable audit link EDGAR offers. SimFin baseline rows
are untouched (they link to the company's filing index by design).

Usage: python -m finclone.pipeline.relink_sources [TICKER ...]  (default: all
SEC-ingested companies)
"""

import sys

from sqlalchemy import select, update

from finclone.db import get_session, init_db
from finclone.edgar.client import EdgarClient
from finclone.edgar.documents import accession_document_map, inline_viewer_url
from finclone.models import Company, FinancialFact


def relink_company(client: EdgarClient, company: Company) -> int:
    with get_session() as session:
        accessions = set(session.scalars(
            select(FinancialFact.accession_number)
            .where(FinancialFact.company_id == company.id)
            .where(FinancialFact.accession_number != "simfin-baseline")
            .distinct()
        ))
    if not accessions:
        return 0

    submissions = client.company_submissions(company.cik)
    documents = accession_document_map(client, company.cik, submissions)

    updated = 0
    with get_session() as session:
        for accn in accessions:
            doc = documents.get(accn)
            if not doc:
                continue  # unresolvable accession keeps its index-page link
            result = session.execute(
                update(FinancialFact)
                .where(FinancialFact.company_id == company.id)
                .where(FinancialFact.accession_number == accn)
                .values(source_url=inline_viewer_url(company.cik, accn, doc))
            )
            updated += result.rowcount
        session.commit()
    return updated


def main() -> None:
    init_db()
    tickers = {t.upper() for t in sys.argv[1:]}
    client = EdgarClient()
    with get_session() as session:
        companies = [
            c for c in session.scalars(select(Company).order_by(Company.ticker))
            if not tickers or c.ticker in tickers
        ]
    for company in companies:
        updated = relink_company(client, company)
        if updated:
            print(f"{company.ticker}: {updated} facts relinked to filing documents")


if __name__ == "__main__":
    main()
