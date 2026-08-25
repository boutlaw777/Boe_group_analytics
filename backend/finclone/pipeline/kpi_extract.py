"""LLM-based extraction of niche KPIs from MD&A/footnotes (PDR §3, NLP engine).

Standard financials come from XBRL (see pipeline.ingest); this module covers
what XBRL doesn't: sector-specific metrics like RevPAR, ARR, or wafer capacity
that companies report only in filing prose. DeepSeek extracts them in JSON
mode, every record is validated defensively, and every value is stored with
the verbatim quote it came from so a human reviewer can verify it against the
filing.

Usage: python -m finclone.pipeline.kpi_extract AAPL [MSFT ...]
       python -m finclone.pipeline.kpi_extract --all [--limit N]
       (requires DEEPSEEK_API_KEY in .env, and the ticker already ingested)

--all sweeps every SEC-extracted company that has no KPIs yet. Each company
costs LLM tokens (up to KPI_MAX_CHUNKS chunks of filing text), so the sweep
is resumable and skips already-covered companies on re-run.
"""

import json
import re
import time
from datetime import date

import openai
from openai import OpenAI
from sqlalchemy import select

from finclone.config import (
    KPI_API_KEY, KPI_BASE_URL, KPI_MAX_CHUNKS, KPI_MODEL, require_bulk_provider)
from finclone.db import get_session, init_db
from finclone.edgar.client import EdgarClient
from finclone.edgar.documents import fetch_filing_text, inline_viewer_url, latest_filing
from finclone.models import Company, KpiFact


class _RateLimited(Exception):
    """The LLM provider's quota is exhausted — stop the sweep so a supervisor
    can resume it after the quota window (per-minute or per-day) resets."""


class _NotIngested(Exception):
    """The ticker resolves to a CIK with no Company row — usually SEC
    ticker->CIK drift since ingest. Skippable in a sweep, fatal for an
    explicitly named ticker."""
from finclone.taxonomy.gics_bridge import industry_for_company
from finclone.taxonomy.kpi_definitions import (
    canonical_name_index, kpis_for_company, resolve_kpi_name)

_CHUNK_SIZE = 15_000  # characters
_CHUNK_OVERLAP = 500

_SYSTEM = """You extract key performance indicators from SEC filing text for a \
financial data platform. Accuracy is critical: every value you report is shown \
to analysts with a link back to the filing.

Rules:
- Only report values that appear explicitly in the provided text. Never estimate, \
compute, or recall values from outside the text.
- The quote field must be copied verbatim from the text and must contain the value.
- Report each distinct (KPI, period) pair once. If the text gives the same KPI for \
multiple periods (e.g. current and prior year), report each period separately.
- Normalize the period field to a canonical form: "Q<n> FY<yyyy>" for a fiscal \
quarter (three-month period), "H1 FY<yyyy>" for a six-month period, "FY<yyyy>" \
for a full year, or "as of <yyyy-mm-dd>" for point-in-time values. Never invent \
other period formats — this prevents duplicate records for the same period.
- Filing tables usually state a scale like "in millions" or "in thousands" in \
their header. Apply it when normalizing "value" (a table cell of 30,976 under \
"in millions" means value 30976000000), and keep value_text as written.
- If none of the target KPIs appear in the text, return {"kpis": []}.

Respond with JSON only, in exactly this shape:
{
  "kpis": [
    {
      "name": "exactly one of the target KPI names, copied verbatim",
      "value": 1200000000,
      "value_text": "the value exactly as written, e.g. $1.2 billion",
      "unit": "USD | rooms | percent | employees | ...",
      "period": "canonical fiscal period, e.g. Q3 FY2025 or FY2025",
      "quote": "verbatim sentence from the document containing this value"
    }
  ]
}
"value" is the number normalized to base units (1.2 billion -> 1200000000); \
use null when the value is not numeric."""


def _select_chunks(text: str, keywords: list[str], max_chunks: int) -> list[str]:
    """Split the filing into overlapping chunks and keep the ones that mention
    the most KPI keywords — cheap pre-filtering so the LLM only reads relevant
    sections of a 300+ page filing."""
    lowered_keywords = [k.lower() for k in keywords]
    scored: list[tuple[int, str]] = []
    step = _CHUNK_SIZE - _CHUNK_OVERLAP
    for start in range(0, len(text), step):
        chunk = text[start:start + _CHUNK_SIZE]
        lower = chunk.lower()
        score = sum(lower.count(k) for k in lowered_keywords)
        if score > 0:
            scored.append((score, chunk))
    scored.sort(key=lambda pair: -pair[0])
    return [chunk for _, chunk in scored[:max_chunks]]


# Unit spellings that mean the same thing. Values are already normalized to
# base units, so this is purely about the label a chart or a peer comparison
# groups on: "$", "USD" and "dollars" splitting one series three ways is the
# same failure as the KPI name doing it.
_UNIT_SYNONYMS: dict[str, str] = {
    "$": "USD", "us$": "USD", "usd": "USD", "dollar": "USD", "dollars": "USD",
    "u.s. dollars": "USD", "us dollars": "USD", "usd millions": "USD",
    "%": "percent", "pct": "percent", "percent": "percent",
    "percentage": "percent", "percentage points": "percent",
    "employee": "employees", "headcount": "employees", "people": "employees",
    "share": "shares", "sq ft": "square feet", "sqft": "square feet",
}

# "Q3 2025", "Q3 FY2025", "third quarter of fiscal 2025" are one period, but
# KpiFact is unique on (company, name, period, accession) — so an unnormalized
# spelling doesn't collide with its twin, it stores a duplicate datapoint and
# breaks the time series. The prompt asks for the canonical form; this is the
# check that it actually arrived in one, since a prompt is a request.
_QUARTER = re.compile(r"^q([1-4])\s*(?:fy)?\s*(\d{4})$")
_HALF = re.compile(r"^h([12])\s*(?:fy)?\s*(\d{4})$")
_FULL_YEAR = re.compile(
    r"^(?:fy|fiscal(?:\s+year)?|full\s+year|year\s+ended)?\s*(\d{4})$")
_ISO_DATE = re.compile(r"^(?:as\s+of\s+)?(\d{4}-\d{2}-\d{2})$")


def normalize_unit(unit: str) -> str:
    """Canonical spelling of a unit, or the unit as written if unrecognized."""
    cleaned = " ".join(unit.strip().split())
    return _UNIT_SYNONYMS.get(cleaned.lower(), cleaned)


def normalize_period(period: str) -> str:
    """Canonical fiscal period, or the period as written if unrecognized.

    Unrecognized is left alone on purpose: a period this can't parse is one a
    reviewer should see in the model's own words, not one to guess at.
    """
    cleaned = " ".join(period.strip().split()).lower().replace("fy ", "fy")
    for pattern, template in ((_QUARTER, "Q{0} FY{1}"), (_HALF, "H{0} FY{1}")):
        match = pattern.match(cleaned)
        if match:
            return template.format(*match.groups())
    match = _ISO_DATE.match(cleaned)
    if match:
        return f"as of {match.group(1)}"
    match = _FULL_YEAR.match(cleaned)
    if match:
        return f"FY{match.group(1)}"
    return " ".join(period.strip().split())


def _clean_kpi(raw: object) -> dict | None:
    """Validate one model-produced record; DeepSeek's JSON mode guarantees
    syntax, not shape, so every field is checked before storage."""
    if not isinstance(raw, dict):
        return None
    name = str(raw.get("name") or "").strip()
    value_text = str(raw.get("value_text") or "").strip()
    period = str(raw.get("period") or "").strip()
    quote = str(raw.get("quote") or "").strip()
    if not (name and value_text and period and quote):
        return None
    value = raw.get("value")
    if isinstance(value, str):
        try:
            value = float(value.replace(",", ""))
        except ValueError:
            value = None
    if not isinstance(value, (int, float)):
        value = None
    return {
        "name": name,
        "value": float(value) if value is not None else None,
        "value_text": value_text,
        "unit": normalize_unit(str(raw.get("unit") or "")),
        "period": normalize_period(period),
        "quote": quote,
    }


def _extract_from_chunk(llm: OpenAI, kpi_labels: list[str], chunk: str) -> list[dict]:
    prompt = (
        "Target KPIs to look for:\n"
        + "\n".join(f"- {label}" for label in kpi_labels)
        + "\n\nFiling excerpt:\n<excerpt>\n"
        + chunk
        + "\n</excerpt>"
    )
    response = llm.chat.completions.create(
        model=KPI_MODEL,
        max_tokens=4096,
        response_format={"type": "json_object"},
        messages=[
            {"role": "system", "content": _SYSTEM},
            {"role": "user", "content": prompt},
        ],
    )
    try:
        data = json.loads(response.choices[0].message.content or "{}")
    except json.JSONDecodeError:
        return []
    raw_kpis = data.get("kpis", []) if isinstance(data, dict) else []
    return [k for k in map(_clean_kpi, raw_kpis) if k is not None]


def extract_ticker(ticker: str, client: EdgarClient, llm: OpenAI) -> None:
    cik = client.ticker_to_cik(ticker)
    with get_session() as session:
        company = session.scalar(select(Company).where(Company.cik == cik))
    if company is None:
        # Not SystemExit: that inherits from BaseException, so the sweep's
        # `except Exception` never caught it and a single unresolvable ticker
        # killed the whole --all run. The supervisor then misreported the
        # non-zero exit as a provider quota and retried hourly, hitting the
        # same ticker forever — the sweep stalled at 521 of 3,010 companies
        # this way. Recoverable per-ticker error instead; main decides.
        raise _NotIngested(ticker.upper())

    submissions = client.company_submissions(cik)
    filing = latest_filing(submissions)
    industry = industry_for_company(company.sic, company.sector)
    print(f"{ticker.upper()}: extracting KPIs from {filing['form']} filed {filing['filed_date']} "
          f"(sector: {company.sector or 'unknown'} | "
          f"GICS: {industry.gics_industry if industry else 'unmapped — generic KPIs only'})")
    text = fetch_filing_text(client, cik, filing)

    kpi_defs = kpis_for_company(company.sic, company.sector)
    keywords = [kw for kpi in kpi_defs for kw in kpi["keywords"]]
    labels = [kpi["label"] for kpi in kpi_defs]
    # The model rewords the target label as often as it echoes it, so the same
    # metric arrived as "RevPAR", "revpar" and "Revenue per available room" and
    # was stored three times. Map whatever it returns back onto this industry's
    # name for the metric; see canonical_name_index for what counts as a match.
    canonical = canonical_name_index(labels)
    chunks = _select_chunks(text, keywords, KPI_MAX_CHUNKS)
    if not chunks:
        print(f"{ticker.upper()}: no KPI-relevant sections found in the filing")
        return

    found: dict[tuple[str, str], dict] = {}
    off_list: dict[str, int] = {}
    for i, chunk in enumerate(chunks, 1):
        print(f"  analyzing section {i}/{len(chunks)}...")
        for attempt in range(4):
            try:
                for kpi in _extract_from_chunk(llm, labels, chunk):
                    stated = kpi["name"].strip()
                    resolved = resolve_kpi_name(stated, canonical)
                    # An unresolved name is kept, not dropped: the model does
                    # surface real KPIs nobody thought to list, and Data Point
                    # Search exists to find exactly those. It is counted below
                    # so the drift is visible instead of silent.
                    kpi["name"] = resolved or stated
                    if resolved is None:
                        off_list[stated] = off_list.get(stated, 0) + 1
                    key = (kpi["name"].lower(), kpi["period"].lower())
                    found.setdefault(key, kpi)
                break
            except openai.RateLimitError:
                # Gemini free tier meters per-minute; back off and retry the
                # same chunk rather than losing it. Only give up after 4 tries.
                if attempt < 3:
                    wait = 20 * (attempt + 1)
                    print(f"  rate limited — waiting {wait}s (retry {attempt + 1}/3)")
                    time.sleep(wait)
                    continue
                print("  still rate limited after retries — stopping early")
                raise _RateLimited()
            except openai.APIStatusError as e:
                if e.status_code == 402:
                    print("  LLM account has insufficient balance — stopping.")
                    raise _RateLimited()
                print(f"  API error {e.status_code} on section {i}: {e.message}")
                break

    source_url = inline_viewer_url(cik, filing["accession_number"], filing["primary_document"])
    inserted = 0
    with get_session() as session:
        existing = {
            (k.name, k.period, k.accession_number)
            for k in session.scalars(select(KpiFact).where(KpiFact.company_id == company.id))
        }
        for kpi in found.values():
            key = (kpi["name"], kpi["period"], filing["accession_number"])
            if key in existing:
                continue
            session.add(KpiFact(
                company_id=company.id,
                name=kpi["name"][:128],
                value=kpi["value"],
                value_text=kpi["value_text"][:128],
                unit=kpi["unit"][:64],
                period=kpi["period"][:64],
                source_quote=kpi["quote"][:1024],
                form=filing["form"],
                accession_number=filing["accession_number"],
                filed_date=date.fromisoformat(filing["filed_date"]),
                source_url=source_url,
            ))
            inserted += 1
        session.commit()

    print(f"{ticker.upper()}: {len(found)} KPIs extracted, {inserted} new stored")
    for kpi in found.values():
        print(f"  {kpi['name']} [{kpi['period']}]: {kpi['value_text']} ({kpi['unit']})")
    if off_list:
        # Named, not just counted: a name that keeps recurring across a sweep is
        # either a KPI the industry's target list is missing or a wording the
        # resolver should learn, and neither is visible from a total.
        names = ", ".join(f"{name} (x{n})" for name, n in sorted(off_list.items()))
        print(f"  note: {len(off_list)} KPI name(s) outside this industry's "
              f"target list, stored as the model worded them — {names}")


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description="LLM extraction of niche KPIs from filing prose")
    parser.add_argument("tickers", nargs="*", help="tickers to extract")
    parser.add_argument("--all", action="store_true",
                        help="every SEC-extracted company that has no KPIs yet "
                             "(costs LLM tokens per company)")
    parser.add_argument("--limit", type=int, default=None,
                        help="with --all: stop after this many companies")
    args = parser.parse_args()
    if not args.tickers and not args.all:
        parser.error("pass tickers or --all")
    require_bulk_provider()
    masked = (f"{KPI_API_KEY[:6]}...{KPI_API_KEY[-4:]}"
              if len(KPI_API_KEY) > 12 else "(too short — check .env)")
    print(f"KPI LLM provider: {KPI_BASE_URL} | model: {KPI_MODEL} | key: {masked}")
    init_db()

    tickers = [t.upper() for t in args.tickers]
    if args.all:
        from finclone.models import FinancialFact

        with get_session() as session:
            sec_ids = set(session.scalars(
                select(FinancialFact.company_id)
                .where(FinancialFact.accession_number != "simfin-baseline")
                .distinct()
            ))
            has_kpis = set(session.scalars(select(KpiFact.company_id).distinct()))
            tickers += [c.ticker
                        for c in session.scalars(select(Company).order_by(Company.ticker))
                        if c.id in sec_ids and c.id not in has_kpis
                        and c.ticker not in tickers]
        if args.limit:
            tickers = tickers[:args.limit]
        print(f"Extracting KPIs for {len(tickers)} SEC-extracted companies without KPIs...")

    client = EdgarClient()
    llm = OpenAI(api_key=KPI_API_KEY, base_url=KPI_BASE_URL, timeout=60, max_retries=1)
    failed = 0
    for i, ticker in enumerate(tickers, start=1):
        try:
            extract_ticker(ticker, client, llm)
        except KeyboardInterrupt:
            print(f"\nStopped at {ticker} ({i - 1}/{len(tickers)} done) — "
                  "re-run to resume; --all skips companies that already have KPIs.")
            return
        except _NotIngested as e:
            if not args.all:
                raise SystemExit(
                    f"{e} is not ingested yet — run: "
                    f"python -m finclone.pipeline.ingest {e}")
            failed += 1
            print(f"{ticker}: not ingested (ticker->CIK drift?) — skipping")
        except _RateLimited:
            # Provider quota exhausted (per-minute burst survived retries, or
            # daily cap). Stop non-zero so the supervisor resumes after reset;
            # --all skips the companies already done this run.
            print(f"LLM quota exhausted at {ticker} "
                  f"({i - 1}/{len(tickers)} processed this run) — "
                  "stopping; re-run after the quota resets.")
            raise SystemExit(3)
        except Exception as e:  # one bad filing must not stop the sweep
            failed += 1
            print(f"{ticker}: KPI extraction failed ({type(e).__name__}: {str(e)[:120]})")
        if args.all and i % 25 == 0:
            print(f"--- {i}/{len(tickers)} ({failed} failed) ---")
    if args.all:
        print(f"Done: {len(tickers)} companies processed, {failed} failed.")


if __name__ == "__main__":
    main()
