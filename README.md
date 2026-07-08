# FinClone

Enterprise FinTech data extraction & Excel modeling platform (Daloopa-class functionality).

## Architecture

```
PDR/
  backend/          Python — data pipeline, taxonomy engine, REST API (Phase 1)
  web/              Next.js — dashboard, Data Sheets UI, Scout, MCP (Phase 2+)
  excel-addin/      Office.js add-in — task pane + custom functions (Phase 3)
```

## Web app (Phase 2)

Requires Node.js 20+ and the backend running on port 8000.

```powershell
cd "C:\Cursor Projects\PDR\web"
npm install
npm run dev
```

Then open http://localhost:3000 — landing page, dashboard with ticker search,
per-company financials (every value hyperlinked to its SEC filing), extracted
KPIs, one-click Data Sheet downloads, custom model templates, and Scout.

## Scout (Phase 3)

Natural-language screening at `/scout` (web) or `GET /scout?q=...` (API).
DeepSeek translates the question into a structured filter spec (sector +
metric thresholds); all metrics are computed from the database — the LLM never
produces numbers. `GET /scout/datapoints?q=...` finds companies reporting a
given niche KPI (the PDR's Data Point Search).

## Phase 1 (current): Data Pipeline & Taxonomy

Strategy: **XBRL-first, NLP-second.** Standard financial statements come from the
SEC's structured `companyfacts` XBRL API (deterministic, near-perfect accuracy).
LLM/NLP extraction is reserved for niche KPIs in MD&A/footnotes (later in Phase 1).

What works today:

- Ticker → CIK resolution via SEC's official mapping
- Company facts ingestion (all historical XBRL facts, all filings)
- Normalization of raw US-GAAP tags → canonical concepts (revenue, net income, …)
- **Point-in-time storage**: every fact keeps its accession number and filed date,
  so original vs. restated values are both queryable
- Derived Q4 values for flow concepts (FY − Q1 − Q2 − Q3)
- Audit trail: every number carries a hyperlink to its source SEC filing
- Industry taxonomy: SIC code → sector mapping, with per-sector KPI definitions
- **LLM KPI extraction**: Claude reads the latest 10-K/10-Q and extracts niche,
  sector-specific KPIs (RevPAR, ARR, wafer capacity, …) that XBRL doesn't carry.
  Every extracted value stores the verbatim source quote for human verification.
- Base REST API: `/companies`, `/companies/{ticker}/financials`,
  `/companies/{ticker}/kpis`
- **Data Sheets (Module 1, early)**: `/companies/{ticker}/datasheet` downloads an
  auditable .xlsx — blue as-reported numbers hyperlinked to their SEC filings,
  black live formulas (margins, FCF), negatives in parentheses, and an
  industry-KPI tab. `?period=quarterly` for the quarterly view.

## Backend setup (run these yourself)

```powershell
cd "C:\Cursor Projects\PDR\backend"
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -e ".[dev]"
copy .env.example .env    # then edit SEC_USER_AGENT if needed
```

Ingest a company, extract KPIs, and start the API:

```powershell
python -m finclone.pipeline.ingest AAPL
python -m finclone.pipeline.kpi_extract AAPL   # needs ANTHROPIC_API_KEY in .env
uvicorn finclone.api.main:app --reload
```

Then open http://127.0.0.1:8000/docs for the interactive API docs.

Run tests:

```powershell
pytest
```

## Notes

- The SEC requires a descriptive `User-Agent` with a contact email and caps
  requests at 10/sec. The client enforces both — set `SEC_USER_AGENT` in `.env`.
- Dev database is SQLite (`finclone.db`); set `DATABASE_URL` to Postgres for prod.
- KPI extraction sends at most `FINCLONE_KPI_MAX_CHUNKS` filing sections to the
  LLM per run (cost control). Extracted KPIs are model output, not audited data —
  the stored `source_quote` exists so a reviewer can verify each value.
- **Filing monitor**: `python -m finclone.pipeline.monitor` checks every tracked
  company for new 10-K/10-Q/8-K filings and re-ingests when found. Run it once
  (schedule with Windows Task Scheduler / cron) or continuously with
  `--watch 10` (poll every 10 minutes). The first pass marks all historical
  filings as seen, so only genuinely new filings trigger work afterwards.
- **Cross-reference validation**: `python -m finclone.pipeline.crossref AAPL`
  compares our SEC-extracted annual values against SimFin (per PDR §3) and
  flags anything with >1% variance for human review. Flags are served at
  `/companies/{ticker}/validation`. Requires `SIMFIN_API_KEY` in `.env`.
- **SimFin bulk baseline** (PDR §3): `python -m finclone.pipeline.simfin_bulk`
  populates the whole SimFin US universe (~4,000 EDGAR-listed companies) with
  standardized annual fundamentals so every company has a working model and
  Data Sheet immediately. Baseline rows are provenance-marked
  (`form="SimFin"`, accession `simfin-baseline`) and always lose to
  SEC-extracted facts, so running the EDGAR ingest on a ticker upgrades it in
  place with filing-level audit links. Resumable — re-running skips companies
  that already have data. `--limit N` for smoke tests, `--quarterly` to
  include Q1–Q3 flows. Scout reads a precomputed `screen_metrics` cache
  (refreshed by every ingest path) so screens stay fast at universe scale.
"# Boe_group_analytics" 
"# Boe_group_analytics" 
