-- BOE Analytics — Supabase schema (Phase 1: no auth, all data shared/global)
-- Run this in the Supabase SQL editor.
--
-- NOTE: RLS is intentionally NOT enabled on these tables for this phase.
-- The app is single-user/no-auth; we will enable RLS when Supabase Auth is added.

-- ============================================================
-- companies
-- ============================================================
create table if not exists companies (
  id          uuid primary key default gen_random_uuid(),
  ticker      text not null unique,
  name        text not null,
  sector      text,
  industry    text,
  simfin_id   integer unique,
  created_at  timestamptz not null default now()
);

create index if not exists idx_companies_ticker on companies (ticker);
create index if not exists idx_companies_sector on companies (sector);

-- ============================================================
-- financials
-- one row per (company, line item, period, fiscal year)
-- ============================================================
create table if not exists financials (
  id            uuid primary key default gen_random_uuid(),
  company_id    uuid not null references companies (id) on delete cascade,
  line_item     text not null,                 -- e.g. 'Revenue', 'Net Income'
  period        text not null,                 -- 'FY', 'Q1', 'Q2', 'Q3', 'Q4'
  fiscal_year   integer not null,
  value         numeric,                       -- null = reported but empty
  is_hardcoded  boolean not null default true, -- true = pulled from source (blue in Excel), false = derived/formula
  source_url    text,                          -- hyperlink target for hardcoded numbers
  updated_at    timestamptz not null default now(),

  constraint financials_unique_datapoint
    unique (company_id, line_item, period, fiscal_year),
  constraint financials_period_check
    check (period in ('FY', 'Q1', 'Q2', 'Q3', 'Q4'))
);

create index if not exists idx_financials_company   on financials (company_id);
create index if not exists idx_financials_lookup    on financials (company_id, fiscal_year, period);
create index if not exists idx_financials_line_item on financials (line_item);

-- ============================================================
-- templates (MCP module — custom row order + formulas)
-- ============================================================
create table if not exists templates (
  id                   uuid primary key default gen_random_uuid(),
  name                 text not null,
  row_mapping_json     jsonb not null default '[]'::jsonb, -- ordered array of line items
  custom_formulas_json jsonb not null default '[]'::jsonb, -- [{name, expression: [{item|op}...]}]
  created_at           timestamptz not null default now()
);

-- ============================================================
-- watchlist (single shared watchlist for this phase)
-- ============================================================
create table if not exists watchlist (
  id          uuid primary key default gen_random_uuid(),
  company_id  uuid not null references companies (id) on delete cascade,
  added_at    timestamptz not null default now(),

  constraint watchlist_unique_company unique (company_id)
);

-- ============================================================
-- api_keys (Developer API module — key validity + tier only)
-- ============================================================
create table if not exists api_keys (
  id             uuid primary key default gen_random_uuid(),
  key            text not null unique,
  tier           text not null default 'free' check (tier in ('free', 'pro')),
  request_count  integer not null default 0,
  revoked        boolean not null default false,
  created_at     timestamptz not null default now()
);

create index if not exists idx_api_keys_key on api_keys (key);

-- Atomic usage counter for the Developer API (called via supabase.rpc()).
create or replace function increment_api_key_count(key_id uuid)
returns void
language sql
as $$
  update api_keys set request_count = request_count + 1 where id = key_id;
$$;
