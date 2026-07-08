"""Screening-metrics cache maintenance.

Scout screens the whole database; computing metrics per company per query
is fine at 5 companies but not at 6,000+ (one DB round-trip each). Every
ingest path calls `refresh_metrics_cache` for the companies it touched, so
Scout can screen from a single cached-table read.

Bulk rebuild (companies whose facts predate the cache, or after data
repairs — run whenever Scout feels slow):
    python -m finclone.scout_cache            # only companies missing a cache row
    python -m finclone.scout_cache --all      # recompute every company
"""

import json
from datetime import date

from sqlalchemy.orm import Session

from finclone.models import ScreenMetrics


def refresh_metrics_cache(session: Session, company_id: int) -> None:
    """Recompute and store the latest-FY screening metrics for one company."""
    # Local imports: scout imports this module's consumers transitively.
    from finclone.pipeline.crossref import _our_annual_values
    from finclone.scout import compute_metrics

    metrics = compute_metrics(_our_annual_values(company_id))
    _store(session, company_id, metrics, session.get(ScreenMetrics, company_id))


def _store(session: Session, company_id: int, metrics: dict | None,
           row: ScreenMetrics | None) -> None:
    # A company with no usable annual data still gets a cache row (JSON null,
    # which run_screen skips): without one, every Scout query falls back to a
    # per-company DB round-trip — 469 no-revenue companies made each screen
    # take minutes.
    payload = json.dumps(metrics)
    fiscal_year = int(metrics["fiscal_year"]) if metrics else 0
    if row is None:
        session.add(ScreenMetrics(
            company_id=company_id,
            fiscal_year=fiscal_year,
            metrics_json=payload,
            updated=date.today(),
        ))
    else:
        row.fiscal_year = fiscal_year
        row.metrics_json = payload
        row.updated = date.today()


def main() -> None:
    import argparse

    from sqlalchemy import select

    from finclone.db import get_session, init_db
    from finclone.models import Company

    parser = argparse.ArgumentParser(description="Rebuild the Scout metrics cache")
    parser.add_argument("--all", action="store_true",
                        help="recompute every company (default: only missing ones)")
    args = parser.parse_args()

    init_db()
    with get_session() as session:
        companies = [c.id for c in session.scalars(select(Company))]
        if not args.all:
            cached = {row.company_id for row in session.scalars(select(ScreenMetrics))}
            companies = [cid for cid in companies if cid not in cached]

    print(f"Refreshing metrics cache for {len(companies)} companies...")
    # Bulk path: fetch facts for hundreds of companies per query instead of
    # one round-trip each — the per-company path takes ~1s/company against a
    # cloud database.
    from finclone.models import FinancialFact
    from finclone.pipeline.crossref import _annual_facts_from_rows
    from finclone.scout import compute_metrics

    CHUNK = 300
    done = 0
    with get_session() as session:
        for start in range(0, len(companies), CHUNK):
            chunk = companies[start:start + CHUNK]
            by_company: dict[int, list[FinancialFact]] = {cid: [] for cid in chunk}
            for f in session.scalars(select(FinancialFact)
                                     .where(FinancialFact.company_id.in_(chunk))):
                by_company[f.company_id].append(f)
            existing = {r.company_id: r for r in session.scalars(
                select(ScreenMetrics).where(ScreenMetrics.company_id.in_(chunk)))}
            for cid in chunk:
                annual = {key: f.value
                          for key, f in _annual_facts_from_rows(by_company[cid]).items()}
                _store(session, cid, compute_metrics(annual), existing.get(cid))
                done += 1
            session.commit()
            print(f"  {done}/{len(companies)}")
    print(f"Done: {done} companies cached. Scout now screens from a single table read.")


if __name__ == "__main__":
    main()
