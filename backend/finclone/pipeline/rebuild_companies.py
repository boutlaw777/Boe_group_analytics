"""Disaster recovery: rebuild the companies table from financial_facts.

For when the companies table has been dropped or replaced by a foreign
schema (e.g. an external import script). Every fact row's source_url embeds
the company's CIK — SEC facts in the EDGAR path, SimFin baseline facts in a
CIK= query parameter — so company identity is fully recoverable:

    company_id -> CIK (from facts) -> ticker + name (SEC's official mapping)

Rows are re-inserted with their ORIGINAL integer ids, so kpi_facts,
screen_metrics, validation_flags and every other company_id reference keeps
working unchanged. Sectors are re-fetched from SEC submissions with
--sectors (~10 req/s, a few minutes per thousand companies).

Usage:
    python -m finclone.pipeline.rebuild_companies            # identity only
    python -m finclone.pipeline.rebuild_companies --sectors  # + sector pass
"""

import argparse
import re
import time

from sqlalchemy import inspect, select, text

from finclone.db import engine, get_session, init_db
from finclone.edgar.client import EdgarClient
from finclone.models import Company, FinancialFact
from finclone.taxonomy.sic_map import sector_for_sic

_CIK_PATTERNS = (re.compile(r"/data/(\d+)/"), re.compile(r"CIK=0*(\d+)"))


def _quarantine_foreign_table(name: str, required_column: str) -> bool:
    """If `name` exists but lacks `required_column`, it's not ours — rename it
    aside (kept for inspection). Returns True if the proper table is absent
    and must be recreated."""
    inspector = inspect(engine)
    if name not in inspector.get_table_names():
        return True
    columns = {c["name"] for c in inspector.get_columns(name)}
    if required_column in columns:
        return False  # the real table is present
    quarantine = f"{name}_rogue_{int(time.time())}"
    print(f"  {name}: foreign schema detected (no '{required_column}' column) "
          f"— renaming to {quarantine}")
    with engine.begin() as conn:
        conn.execute(text(f'alter table "{name}" rename to "{quarantine}"'))
    return True


def _extract_cik(url: str) -> int | None:
    for pattern in _CIK_PATTERNS:
        match = pattern.search(url or "")
        if match:
            return int(match.group(1))
    return None


def main() -> None:
    parser = argparse.ArgumentParser(description="Rebuild companies from financial_facts")
    parser.add_argument("--sectors", action="store_true",
                        help="also re-fetch SIC/sector from SEC submissions (slower)")
    args = parser.parse_args()

    print("Step 1: quarantining foreign tables if present...")
    _quarantine_foreign_table("companies", "cik")
    _quarantine_foreign_table("api_keys", "key_hash")

    print("Step 2: recreating missing tables from our schema...")
    init_db()  # create_all: only creates what's absent

    print("Step 3: recovering company identities from financial_facts...")
    with get_session() as session:
        already = {c.id for c in session.scalars(select(Company))}
        rows = session.execute(
            select(FinancialFact.company_id, FinancialFact.source_url).distinct()
        ).all()

    cik_by_id: dict[int, int] = {}
    for company_id, url in rows:
        if company_id in cik_by_id or company_id in already:
            continue
        cik = _extract_cik(url)
        if cik is not None:
            cik_by_id[company_id] = cik
    print(f"  {len(cik_by_id)} companies recoverable "
          f"({len(already)} already present and kept)")

    client = EdgarClient()
    # A CIK can list several tickers (share classes, preferreds, warrants);
    # SEC orders the primary common ticker first, so keep the first entry.
    sec_map: dict[int, tuple[str, str]] = {}
    for e in client.get_json("https://www.sec.gov/files/company_tickers.json").values():
        sec_map.setdefault(int(e["cik_str"]), (e["ticker"], e["title"]))

    inserted = 0
    skipped = 0
    used_tickers: set[str] = set()
    used_ciks: set[str] = set()
    with get_session() as session:
        for c in session.scalars(select(Company)):
            used_tickers.add(c.ticker)
            used_ciks.add(c.cik)

        def _flush_batch(batch: list[Company]) -> tuple[int, int]:
            """Commit a batch; on failure retry row-by-row so one bad row
            can't abort the rebuild. Returns (ok, failed)."""
            nonlocal session
            session.add_all(batch)
            try:
                session.commit()
                return len(batch), 0
            except Exception:
                session.rollback()
                ok = failed = 0
                for row in batch:
                    session.add(row)
                    try:
                        session.commit()
                        ok += 1
                    except Exception as e:
                        session.rollback()
                        failed += 1
                        print(f"  SKIP id={row.id} ticker={row.ticker}: "
                              f"{type(e).__name__}: {str(e).splitlines()[0][:120]}")
                return ok, failed

        batch: list[Company] = []
        for company_id, cik in sorted(cik_by_id.items()):
            cik_str = f"{cik:010d}"
            if cik_str in used_ciks:
                skipped += 1  # two old ids resolved to one CIK — keep the first
                continue
            ticker, name = sec_map.get(cik, (None, None))
            if ticker is None or ticker in used_tickers:
                # Delisted / not in today's SEC mapping, or ticker collision:
                # keep the row addressable via a synthetic ticker. Unpadded so
                # it fits the 12-char ticker column ("CIK1866368").
                ticker = f"CIK{cik}"[:12]
                if ticker in used_tickers:
                    skipped += 1
                    continue
                name = name or ticker
            used_tickers.add(ticker)
            used_ciks.add(cik_str)
            batch.append(Company(id=company_id, cik=cik_str,
                                 ticker=ticker, name=(name or ticker)[:255],
                                 sic=None, sector=None))
            if len(batch) >= 100:
                ok, failed = _flush_batch(batch)
                inserted += ok
                skipped += failed
                batch = []
                if inserted % 500 < 100:
                    print(f"  {inserted} companies rebuilt...")
        if batch:
            ok, failed = _flush_batch(batch)
            inserted += ok
            skipped += failed
        # Explicit-id inserts bypass the sequence; realign it.
        session.execute(text(
            "select setval(pg_get_serial_sequence('companies','id'), "
            "(select coalesce(max(id), 1) from companies))"
        ))
        session.commit()
    print(f"  {inserted} companies rebuilt with their original ids "
          f"({skipped} skipped — details above)")

    if args.sectors:
        print("Step 4: re-fetching sectors from SEC submissions (throttled)...")
        with get_session() as session:
            todo = [(c.id, c.cik, c.ticker) for c in session.scalars(
                select(Company).where(Company.sector.is_(None)))]
        done = 0
        consecutive_failures = 0
        with get_session() as session:
            for company_id, cik, ticker in todo:
                try:
                    submissions = client.company_submissions(cik)
                    sic = str(submissions.get("sic") or "") or None
                    company = session.get(Company, company_id)
                    if company is None:
                        raise RuntimeError("company row vanished mid-run")
                    company.sic = sic
                    company.sector = sector_for_sic(sic)
                    session.commit()  # per-row: one failure can't poison the rest
                    consecutive_failures = 0
                except Exception as e:
                    session.rollback()
                    consecutive_failures += 1
                    reason = f"{type(e).__name__}: {str(e).splitlines()[0][:120]}"
                    print(f"  {ticker}: sector fetch failed ({reason}) — left null")
                    if "UndefinedColumn" in reason or consecutive_failures >= 10:
                        print("\n  ABORTING: the companies table appears to have been "
                              "replaced again mid-run. Lock out the intruder (cron "
                              "job / credentials), then re-run this script.")
                        return
                done += 1
                if done % 200 == 0:
                    print(f"  {done}/{len(todo)} sectors restored...")
        print(f"  sectors restored for {done} companies")

    print("\nDone. Remaining manual steps:")
    print("  1. Restart the backend servers")
    print("  2. Recreate an API key via POST /admin/keys (the old one was lost)")
    print("  3. If sectors were skipped, re-run with --sectors when convenient")


if __name__ == "__main__":
    main()
