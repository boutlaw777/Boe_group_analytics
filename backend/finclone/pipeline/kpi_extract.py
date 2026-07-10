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
import sys
from datetime import date

import openai
from openai import OpenAI
from sqlalchemy import select

from finclone.config import DEEPSEEK_API_KEY, DEEPSEEK_BASE_URL, KPI_MAX_CHUNKS, KPI_MODEL
from finclone.db import get_session, init_db
from finclone.edgar.client import EdgarClient
from finclone.edgar.documents import fetch_filing_text, inline_viewer_url, latest_filing
from finclone.models import Company, KpiFact
from finclone.taxonomy.kpi_definitions import kpis_for_sector

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
      "name": "canonical KPI name from the target list",
      "value": 1200000000,
      "value_text": "the value exactly as written, e.g. $1.2 billion",
      "unit": "USD | rooms | percent | employees | ...",
      "period": "fiscal period as stated, e.g. Q3 2025 or fiscal year 2025",
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
        "unit": str(raw.get("unit") or "").strip(),
        "period": period,
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
        raise SystemExit(
            f"{ticker.upper()} is not ingested yet — run: python -m finclone.pipeline.ingest {ticker.upper()}"
        )

    submissions = client.company_submissions(cik)
    filing = latest_filing(submissions)
    print(f"{ticker.upper()}: extracting KPIs from {filing['form']} filed {filing['filed_date']} "
          f"(sector: {company.sector or 'unknown'})")
    text = fetch_filing_text(client, cik, filing)

    kpi_defs = kpis_for_sector(company.sector)
    keywords = [kw for kpi in kpi_defs for kw in kpi["keywords"]]
    labels = [kpi["label"] for kpi in kpi_defs]
    chunks = _select_chunks(text, keywords, KPI_MAX_CHUNKS)
    if not chunks:
        print(f"{ticker.upper()}: no KPI-relevant sections found in the filing")
        return

    found: dict[tuple[str, str], dict] = {}
    for i, chunk in enumerate(chunks, 1):
        print(f"  analyzing section {i}/{len(chunks)}...")
        try:
            for kpi in _extract_from_chunk(llm, labels, chunk):
                key = (kpi["name"].lower(), kpi["period"].lower())
                found.setdefault(key, kpi)
        except openai.RateLimitError:
            print("  rate limited — stopping early with results so far")
            break
        except openai.APIStatusError as e:
            if e.status_code == 402:
                print("  DeepSeek account has insufficient balance — top up at "
                      "https://platform.deepseek.com (Billing). Stopping.")
                break
            print(f"  API error {e.status_code} on section {i}: {e.message}")
            continue

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
    if not DEEPSEEK_API_KEY:
        raise SystemExit(
            "DEEPSEEK_API_KEY is not set. Add this line to backend\\.env:\n"
            "  DEEPSEEK_API_KEY=sk-your-key-here"
        )
    masked = (f"{DEEPSEEK_API_KEY[:8]}...{DEEPSEEK_API_KEY[-4:]}"
              if len(DEEPSEEK_API_KEY) > 12 else "(too short — check .env)")
    print(f"LLM provider: {DEEPSEEK_BASE_URL} | model: {KPI_MODEL} | key: {masked}")
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
    llm = OpenAI(api_key=DEEPSEEK_API_KEY, base_url=DEEPSEEK_BASE_URL)
    failed = 0
    for i, ticker in enumerate(tickers, start=1):
        try:
            extract_ticker(ticker, client, llm)
        except KeyboardInterrupt:
            print(f"\nStopped at {ticker} ({i - 1}/{len(tickers)} done) — "
                  "re-run to resume; --all skips companies that already have KPIs.")
            return
        except Exception as e:  # one bad filing must not stop the sweep
            failed += 1
            print(f"{ticker}: KPI extraction failed ({type(e).__name__}: {str(e)[:120]})")
        if args.all and i % 25 == 0:
            print(f"--- {i}/{len(tickers)} ({failed} failed) ---")
    if args.all:
        print(f"Done: {len(tickers)} companies processed, {failed} failed.")


if __name__ == "__main__":
    main()
