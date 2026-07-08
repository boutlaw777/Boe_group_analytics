"""Throttled HTTP client for SEC EDGAR endpoints.

The SEC's fair-access policy requires a descriptive User-Agent with a contact
email and caps clients at 10 requests/second.
"""

import time

import httpx

from finclone.config import SEC_MIN_REQUEST_INTERVAL, SEC_USER_AGENT

_HEADERS = {"User-Agent": SEC_USER_AGENT, "Accept-Encoding": "gzip, deflate"}
_MAX_RETRIES = 3


class EdgarClient:
    def __init__(self) -> None:
        self._client = httpx.Client(headers=_HEADERS, timeout=30.0, follow_redirects=True)
        self._last_request_at = 0.0

    def _throttle(self) -> None:
        elapsed = time.monotonic() - self._last_request_at
        if elapsed < SEC_MIN_REQUEST_INTERVAL:
            time.sleep(SEC_MIN_REQUEST_INTERVAL - elapsed)
        self._last_request_at = time.monotonic()

    def get_json(self, url: str) -> dict:
        for attempt in range(_MAX_RETRIES):
            self._throttle()
            response = self._client.get(url)
            if response.status_code == 429 or response.status_code >= 500:
                time.sleep(2**attempt)
                continue
            response.raise_for_status()
            return response.json()
        response.raise_for_status()
        return response.json()

    def get_text(self, url: str) -> str:
        for attempt in range(_MAX_RETRIES):
            self._throttle()
            response = self._client.get(url)
            if response.status_code == 429 or response.status_code >= 500:
                time.sleep(2**attempt)
                continue
            response.raise_for_status()
            return response.text
        response.raise_for_status()
        return response.text

    # --- EDGAR endpoints -------------------------------------------------

    def ticker_to_cik(self, ticker: str) -> str:
        """Resolve a ticker to a zero-padded 10-digit CIK."""
        data = self.get_json("https://www.sec.gov/files/company_tickers.json")
        ticker = ticker.upper()
        for entry in data.values():
            if entry["ticker"] == ticker:
                return f"{entry['cik_str']:010d}"
        raise ValueError(f"Ticker not found on EDGAR: {ticker}")

    def company_facts(self, cik: str) -> dict:
        """All XBRL facts ever reported by the company, grouped by taxonomy tag."""
        return self.get_json(f"https://data.sec.gov/api/xbrl/companyfacts/CIK{cik}.json")

    def company_submissions(self, cik: str) -> dict:
        """Company metadata (name, SIC code) and recent filing history."""
        return self.get_json(f"https://data.sec.gov/submissions/CIK{cik}.json")


def filing_index_url(cik: str, accession_number: str) -> str:
    """URL of the filing's document index page — the audit-trail link target."""
    accn = accession_number.replace("-", "")
    return f"https://www.sec.gov/Archives/edgar/data/{int(cik)}/{accn}/"
