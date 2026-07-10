"""Auto-restore hijacked tables (the shared-DB re-seeder incident).

An external legacy deployment periodically renames our companies/api_keys
tables to *_backup_20260707 and installs its own 4-row seed schema. Until its
database password is rotated, any long pipeline run can crash mid-flight.
This check runs before (and between) pipeline phases: if a table has been
swapped, drop the impostor and rename ours back. No-op when all is healthy.

Usage: python -m finclone.pipeline.recover_tables
Exit code 0 = healthy or restored; 1 = broken and NOT restorable.
"""

import sys

from sqlalchemy import inspect, text

from finclone.db import engine

# table -> a column only OUR schema has
_OURS = {"companies": "cik", "api_keys": "key_hash"}
_BACKUP_SUFFIX = "_backup_20260707"  # the intruder's rename target, observed 3x


def _columns(inspector, table: str) -> set[str]:
    return {c["name"] for c in inspector.get_columns(table)}


def main() -> None:
    inspector = inspect(engine)
    tables = set(inspector.get_table_names())
    broken = []
    for table, marker in _OURS.items():
        backup = table + _BACKUP_SUFFIX
        ours_in_place = table in tables and marker in _columns(inspector, table)
        if ours_in_place:
            continue
        if backup in tables and marker in _columns(inspector, backup):
            with engine.begin() as conn:
                if table in tables:
                    conn.execute(text(f'drop table "{table}" cascade'))
                conn.execute(text(f'alter table "{backup}" rename to "{table}"'))
            print(f"[recover] {table}: hijacked — restored from {backup}")
        elif table in tables:
            print(f"[recover] {table}: foreign schema and no backup found — "
                  "manual repair needed (rebuild_companies)")
            broken.append(table)
        else:
            print(f"[recover] {table}: missing entirely — manual repair needed")
            broken.append(table)
    if not broken:
        print("[recover] all tables healthy")
    sys.exit(1 if broken else 0)


if __name__ == "__main__":
    main()
