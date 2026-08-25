"""Restandardize KPI names, periods and units on already-extracted rows.

`kpi_extract` now maps every model-returned name back onto the industry's own
name for the metric (`canonical_name_index`), and normalizes the period and
unit. Rows extracted before that landed under whatever wording the filing used
— one hotel's RevPAR under "RevPAR", the next under "Revenue per available
room" — which is invisible in a single company view and breaks the moment
anyone compares the metric across an industry or searches for it by name.

This rewrites those rows in place. It is not a re-extraction: values, quotes
and audit links are untouched, only the labels they are filed under.

Merging is the reason this defaults to a dry run. KpiFact is unique on
(company, name, period, accession), so renaming can collide with a row that
already holds the canonical name — the same datapoint, recorded twice under two
spellings. The collision is resolved by keeping one row and deleting the other,
and deleting extracted data is not something to do without looking first.

Usage: python -m finclone.pipeline.normalize_kpis [TICKER ...]     # dry run
       python -m finclone.pipeline.normalize_kpis --apply [TICKER ...]
"""

import sys

from sqlalchemy import select

from finclone.db import get_session, init_db
from finclone.models import Company, KpiFact
from finclone.pipeline.kpi_extract import normalize_period, normalize_unit
from finclone.taxonomy.kpi_definitions import (
    canonical_name_index, kpis_for_company, resolve_kpi_name)


def plan_company(session, company: Company) -> tuple[list[tuple], list[KpiFact]]:
    """(renames, deletions) for one company, without touching the database.

    A rename whose target key is already taken is a duplicate of that row, so
    the newer of the two is dropped. Ordering by id keeps "newer" stable rather
    than dependent on how the rows came back.
    """
    labels = [kpi["label"] for kpi in kpis_for_company(company.sic, company.sector)]
    index = canonical_name_index(labels)

    rows = list(session.scalars(
        select(KpiFact).where(KpiFact.company_id == company.id).order_by(KpiFact.id)))
    taken: dict[tuple[str, str, str], KpiFact] = {}
    renames: list[tuple] = []
    deletions: list[KpiFact] = []

    for row in rows:
        name = resolve_kpi_name(row.name, index) or row.name
        period = normalize_period(row.period)
        unit = normalize_unit(row.unit)
        key = (name, period, row.accession_number)
        if key in taken:
            # Same datapoint, two spellings. Keep whichever arrived first; the
            # quote and source_url on both point at the same filing text.
            deletions.append(row)
            continue
        taken[key] = row
        if (name, period, unit) != (row.name, row.period, row.unit):
            renames.append((row, name, period, unit))
    return renames, deletions


def main() -> None:
    init_db()
    args = sys.argv[1:]
    apply = "--apply" in args
    tickers = {a.upper() for a in args if not a.startswith("--")}

    renamed = removed = 0
    with get_session() as session:
        companies = [
            c for c in session.scalars(select(Company).order_by(Company.ticker))
            if not tickers or c.ticker in tickers
        ]
        for company in companies:
            renames, deletions = plan_company(session, company)
            if not renames and not deletions:
                continue
            print(f"{company.ticker}: {len(renames)} to restandardize, "
                  f"{len(deletions)} duplicate row(s) to merge")
            for row, name, period, unit in renames:
                if (row.name, row.period) != (name, period):
                    print(f"  {row.name!r} [{row.period}] -> {name!r} [{period}]")
                if apply:
                    row.name, row.period, row.unit = name[:128], period[:64], unit[:64]
            for row in deletions:
                print(f"  drop duplicate {row.name!r} [{row.period}] id={row.id}")
                if apply:
                    session.delete(row)
            renamed += len(renames)
            removed += len(deletions)
        if apply:
            session.commit()

    verb = "restandardized" if apply else "would restandardize"
    print(f"\n{verb} {renamed} KPI row(s); "
          f"{'merged' if apply else 'would merge'} {removed} duplicate(s)")
    if not apply and (renamed or removed):
        print("Dry run — re-run with --apply to write these changes.")


if __name__ == "__main__":
    main()
