"""Ingestion status report: how much data is in the database right now.

Run it on the VPS (or anywhere with DATABASE_URL set) to check on a bulk
ingest without interrupting it — it only reads.

Usage:
    python -m finclone.pipeline.stats
"""

from sqlalchemy import func, select

from finclone.db import engine, get_session, init_db
from finclone.models import (
    Company,
    FinancialFact,
    KpiFact,
    SeenFiling,
    ValidationFlag,
)

_BASELINE_ACCESSION = "simfin-baseline"


def _database_size(session) -> str | None:
    """Human-readable on-disk size, when the backend can report one."""
    if engine.dialect.name == "postgresql":
        return session.execute(
            select(func.pg_size_pretty(func.pg_database_size(func.current_database())))
        ).scalar_one()
    if engine.dialect.name == "sqlite":
        size = session.connection().exec_driver_sql(
            "SELECT page_count * page_size FROM pragma_page_count(), pragma_page_size()"
        ).scalar()
        return f"{size / 1_048_576:.1f} MB"
    return None


def main() -> None:
    init_db()
    with get_session() as session:
        companies = session.scalar(select(func.count()).select_from(Company))

        sec_companies = session.scalar(
            select(func.count(func.distinct(FinancialFact.company_id)))
            .where(FinancialFact.accession_number != _BASELINE_ACCESSION)
        )
        baseline_only = session.scalar(
            select(func.count(func.distinct(FinancialFact.company_id)))
        ) - sec_companies

        facts = session.scalar(select(func.count()).select_from(FinancialFact))
        sec_facts = session.scalar(
            select(func.count()).select_from(FinancialFact)
            .where(FinancialFact.accession_number != _BASELINE_ACCESSION)
        )
        derived = session.scalar(
            select(func.count()).select_from(FinancialFact)
            .where(FinancialFact.derived.is_(True))
        )
        latest_filed = session.scalar(select(func.max(FinancialFact.filed_date)))
        year_lo, year_hi = session.execute(
            select(func.min(FinancialFact.fiscal_year), func.max(FinancialFact.fiscal_year))
        ).one()

        kpis = session.scalar(select(func.count()).select_from(KpiFact))
        kpi_companies = session.scalar(select(func.count(func.distinct(KpiFact.company_id))))
        seen = session.scalar(select(func.count()).select_from(SeenFiling))
        open_flags = session.scalar(
            select(func.count()).select_from(ValidationFlag)
            .where(ValidationFlag.resolved.is_(False))
        )
        db_size = _database_size(session)

    print("=== FinClone ingestion status ===")
    print(f"Companies:            {companies:,}")
    print(f"  SEC-extracted:      {sec_companies:,}")
    print(f"  SimFin-baseline:    {baseline_only:,}")
    print(f"Financial facts:      {facts:,}")
    print(f"  from SEC filings:   {sec_facts:,}")
    print(f"  derived (e.g. Q4):  {derived:,}")
    if year_lo is not None:
        print(f"  fiscal years:       {year_lo}-{year_hi}")
    if latest_filed is not None:
        print(f"  latest filed date:  {latest_filed}")
    print(f"KPI facts (LLM):      {kpis:,} across {kpi_companies:,} companies")
    print(f"Seen filings:         {seen:,}")
    print(f"Open validation flags: {open_flags:,}")
    if db_size:
        print(f"Database size:        {db_size}")


if __name__ == "__main__":
    main()
