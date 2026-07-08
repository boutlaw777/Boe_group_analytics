"""Raw-filing archive on Supabase Storage (PDR §3).

The PDR specifies archiving raw filing HTML to AWS S3; Supabase Storage is
S3-compatible object storage and consolidates infrastructure on one vendor.
Audit-trail hyperlinks keep pointing at sec.gov (the authoritative source);
the archive is our durability copy.

Layout in the bucket: {TICKER}/{accession-number}/{primary-document}

Usage: python -m finclone.pipeline.archive AAPL [MSFT ...] [--forms 10-K,10-Q,8-K] [--limit 5]
"""

import argparse

import httpx

from finclone.config import ARCHIVE_BUCKET, SUPABASE_SECRET_KEY, SUPABASE_URL
from finclone.edgar.client import EdgarClient
from finclone.edgar.documents import filing_document_url

_DEFAULT_FORMS = ("10-K", "10-Q", "8-K")


def recent_filings(submissions: dict, forms: tuple[str, ...], limit: int) -> list[dict]:
    """The newest `limit` filings of the given form types (newest first)."""
    recent = submissions.get("filings", {}).get("recent", {})
    out: list[dict] = []
    for i, form in enumerate(recent.get("form", [])):
        if form in forms:
            out.append({
                "form": form,
                "accession_number": recent["accessionNumber"][i],
                "primary_document": recent["primaryDocument"][i],
                "filed_date": recent["filingDate"][i],
            })
            if len(out) >= limit:
                break
    return out


def upload_to_storage(http: httpx.Client, path: str, content: bytes,
                      content_type: str = "text/html") -> None:
    """PUT an object into the archive bucket (upsert — re-runs are idempotent)."""
    resp = http.post(
        f"{SUPABASE_URL}/storage/v1/object/{ARCHIVE_BUCKET}/{path}",
        content=content,
        headers={
            # New-format Supabase secret keys (sb_secret_...) are not JWTs;
            # storage auth requires them in the apikey header. The Bearer
            # header keeps legacy service-role JWT keys working.
            "apikey": SUPABASE_SECRET_KEY,
            "Authorization": f"Bearer {SUPABASE_SECRET_KEY}",
            "Content-Type": content_type,
            "x-upsert": "true",
        },
        timeout=60.0,
    )
    if resp.status_code not in (200, 201):
        raise RuntimeError(f"Storage upload failed ({resp.status_code}): {resp.text[:200]}")


def archive_ticker(edgar: EdgarClient, http: httpx.Client, ticker: str,
                   forms: tuple[str, ...], limit: int) -> None:
    ticker = ticker.upper()
    cik = edgar.ticker_to_cik(ticker)
    submissions = edgar.company_submissions(cik)
    filings = recent_filings(submissions, forms, limit)
    if not filings:
        print(f"{ticker}: no {'/'.join(forms)} filings found")
        return

    archived = 0
    for f in filings:
        url = filing_document_url(cik, f["accession_number"], f["primary_document"])
        html = edgar.get_text(url)
        path = f"{ticker}/{f['accession_number']}/{f['primary_document']}"
        upload_to_storage(http, path, html.encode("utf-8"))
        archived += 1
        print(f"  {f['form']} {f['filed_date']} -> {ARCHIVE_BUCKET}/{path}")
    print(f"{ticker}: {archived} filings archived")


def main() -> None:
    parser = argparse.ArgumentParser(description="Archive raw SEC filings to Supabase Storage")
    parser.add_argument("tickers", nargs="+")
    parser.add_argument("--forms", default=",".join(_DEFAULT_FORMS),
                        help="Comma-separated form types (default: 10-K,10-Q,8-K)")
    parser.add_argument("--limit", type=int, default=5,
                        help="Max filings per ticker, newest first (default: 5)")
    args = parser.parse_args()

    if not SUPABASE_URL or not SUPABASE_SECRET_KEY:
        raise SystemExit("SUPABASE_URL and SUPABASE_SECRET_KEY must be set in backend\\.env")

    forms = tuple(f.strip().upper() for f in args.forms.split(",") if f.strip())
    edgar = EdgarClient()
    with httpx.Client() as http:
        for ticker in args.tickers:
            archive_ticker(edgar, http, ticker, forms, args.limit)


if __name__ == "__main__":
    main()
