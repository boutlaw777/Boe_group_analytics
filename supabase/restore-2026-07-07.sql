-- Restore script — 2026-07-07
-- The app's `companies` and `api_keys` tables were dropped and recreated with
-- a different schema (integer ids, cik/sic, hashed keys), which breaks every
-- page with: "column companies.industry does not exist".
--
-- This script is NON-DESTRUCTIVE: the unexpected tables are renamed aside
-- (suffix _backup_20260707), the app schema is recreated per schema.sql, and
-- the four cached companies are re-inserted with their ORIGINAL uuids so the
-- existing rows in `financials` and `watchlist` re-link automatically.
--
-- Run this once in the Supabase SQL editor.

-- 1. Move the unexpected tables aside (kept, not deleted)
alter table if exists companies rename to companies_backup_20260707;
alter table if exists api_keys  rename to api_keys_backup_20260707;

-- Rename indexes of the backup tables to prevent name conflicts
alter index if exists idx_companies_ticker rename to idx_companies_backup_20260707_ticker;
alter index if exists idx_companies_sector rename to idx_companies_backup_20260707_sector;
alter index if exists idx_api_keys_key rename to idx_api_keys_backup_20260707_key;


-- 2. Recreate `companies` (as in schema.sql)
create table companies (
  id          uuid primary key default gen_random_uuid(),
  ticker      text not null unique,
  name        text not null,
  sector      text,
  industry    text,
  simfin_id   integer unique,
  created_at  timestamptz not null default now()
);

create index idx_companies_ticker on companies (ticker);
create index idx_companies_sector on companies (sector);

-- 3. Recreate `api_keys` (as in schema.sql)
create table api_keys (
  id             uuid primary key default gen_random_uuid(),
  key            text not null unique,
  tier           text not null default 'free' check (tier in ('free', 'pro')),
  request_count  integer not null default 0,
  revoked        boolean not null default false,
  created_at     timestamptz not null default now()
);

create index idx_api_keys_key on api_keys (key);

create or replace function increment_api_key_count(key_id uuid)
returns void
language sql
as $$
  update api_keys set request_count = request_count + 1 where id = key_id;
$$;

-- 4. Restore the four cached companies with their original ids
--    (ids recovered from the app's own API responses on 2026-07-06;
--     simfin_ids re-fetched from SimFin)
insert into companies (id, ticker, name, sector, industry, simfin_id) values
  ('916551e2-ba0e-4c16-95a6-bb005ed86091', 'AAPL', 'APPLE INC',         'Computer Hardware',    'Technology', 111052),
  ('bf5d3c64-f32f-45e5-9f3e-32d28ad85a22', 'GOOG', 'Alphabet (Google)', 'Online Media',         'Technology', 18),
  ('0ed721f0-a7ed-4a71-9126-01317ab222e7', 'MSFT', 'MICROSOFT CORP',    'Application Software', 'Technology', 59265),
  ('37c4dd05-0500-46de-83f8-a004f5d6302b', 'NVDA', 'NVIDIA CORP',       'Semiconductors',       'Technology', 172199)
on conflict (ticker) do nothing;

-- 5. Re-attach the foreign keys that were dropped along with the old table
do $$
begin
  if not exists (select 1 from pg_constraint where conname = 'financials_company_id_fkey') then
    alter table financials
      add constraint financials_company_id_fkey
      foreign key (company_id) references companies (id) on delete cascade;
  end if;
  if not exists (select 1 from pg_constraint where conname = 'watchlist_company_id_fkey') then
    alter table watchlist
      add constraint watchlist_company_id_fkey
      foreign key (company_id) references companies (id) on delete cascade;
  end if;
end $$;
