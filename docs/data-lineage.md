# Data lineage: BOE Analytics vs BOE DCF

Written to answer the Aug 2026 QA review's Analytics improvement #2 —
*"Confirm the Developer/API feed is the same data source powering DCF's
assumptions."*

## The answer: no, they are different vendors

This was the review's most consequential open question, and the honest answer is
that the two platforms have never shared a feed.

| | BOE Analytics (`analytics.boegroup.com`) | BOE DCF (`dcf.boegroup.com`) |
|---|---|---|
| Primary source | SEC EDGAR XBRL `companyfacts` | Financial Modeling Prep (FMP) |
| Secondary | SimFin (cross-reference only, never published) | — |
| Ingest | Batch pipeline into Postgres (`boe` schema) | Live REST fetch per model build |
| Code | `backend/finclone/edgar/`, `pipeline/` | `fable-dcf/src/lib/fmp.ts` |
| Audit trail | Every value links to the filing it came from | Vendor-standardized; no filing link |
| Cross-referenced | Yes — 1% variance threshold, held for review | No |

`GET /companies/{ticker}/financials` (the Developer/API portal feed) serves the
Analytics side of that table. DCF never calls it.

## Why this still matters after Issue #1 was fixed

The fix for the assumption-calibration bug made DCF *self-consistent*: the Base
Case is now derived from the same financials the model displays in its own KPI
panel, so an assumption can no longer contradict the actual on screen.

It did not make DCF consistent with **Analytics**. Both platforms can show a
defensible EBIT margin for the same company and still disagree, because
standardization differs by vendor — exactly the class of difference the
validation queue exists to surface *within* Analytics, and which currently has
no equivalent check *between* the two platforms.

The long-term-debt flags are the worked example of how large that gap can be
without either side being wrong: 78.3B and 90.7B are both Apple's FY2025
long-term debt, under two definitions.

## The decision this leaves open

Pointing DCF at the Analytics feed is not a drop-in change, which is why it is
recorded here rather than done quietly:

- **Coverage.** Analytics only holds companies that have been ingested. FMP
  covers any listed ticker. Switching the feed means a new model for an
  un-ingested ticker fails where it used to work.
- **Freshness.** Analytics is batch-ingested from filings; FMP updates on its
  own schedule. Whichever is chosen, "as of" needs to be visible on the model.
- **Auth.** DCF would need a service API key and to handle the Analytics
  rate-limit tiers.
- **Upside.** Every DCF input would gain a filing-level audit link and pass
  through the validation queue — which is what the review was reaching for.

A middle option, cheaper than a full migration: keep FMP as the source but
reconcile against Analytics at model-build time and flag material differences,
reusing the warning surface that `assumptionValidation.ts` already renders.

Until one of those is chosen, treat a figure that differs between the two
platforms as a vendor-standardization difference, not a defect in either.
