"""Fetch and clean SEC filing documents (the HTML behind 10-K/10-Q filings)."""

import warnings

from bs4 import BeautifulSoup, XMLParsedAsHTMLWarning

# Modern filings are inline-XBRL (XHTML); parsing them with the HTML parser is
# intentional and works fine — silence bs4's advisory about it.
warnings.filterwarnings("ignore", category=XMLParsedAsHTMLWarning)

from finclone.edgar.client import EdgarClient


def latest_filing(submissions: dict, forms: tuple[str, ...] = ("10-K", "10-Q")) -> dict:
    """The most recent filing of the given form types, from a submissions payload.

    The `recent` arrays in the submissions API are parallel lists ordered
    newest-first.
    """
    recent = submissions.get("filings", {}).get("recent", {})
    for i, form in enumerate(recent.get("form", [])):
        if form in forms:
            return {
                "form": form,
                "accession_number": recent["accessionNumber"][i],
                "primary_document": recent["primaryDocument"][i],
                "filed_date": recent["filingDate"][i],
            }
    raise ValueError(f"No {'/'.join(forms)} filing found for this company")


def filing_document_url(cik: str, accession_number: str, primary_document: str) -> str:
    accn = accession_number.replace("-", "")
    return f"https://www.sec.gov/Archives/edgar/data/{int(cik)}/{accn}/{primary_document}"


def inline_viewer_url(cik: str, accession_number: str, primary_document: str) -> str:
    """The SEC's inline-XBRL viewer opened on the filing's primary document.

    This is the deepest stable audit link EDGAR offers: the reader lands in
    the actual 10-K/10-Q with every tagged number clickable/highlightable.
    For pre-inline-XBRL documents the viewer falls back to the plain file."""
    accn = accession_number.replace("-", "")
    return (f"https://www.sec.gov/ix?doc=/Archives/edgar/data/"
            f"{int(cik)}/{accn}/{primary_document}")


def accession_document_map(client: EdgarClient, cik: str, submissions: dict) -> dict[str, str]:
    """accession number -> primary document filename, across the company's
    entire filing history (the `recent` block plus paginated archive files)."""
    mapping: dict[str, str] = {}

    def fold(block: dict) -> None:
        accessions = block.get("accessionNumber", [])
        documents = block.get("primaryDocument", [])
        for accn, doc in zip(accessions, documents):
            if doc:
                mapping[accn] = doc

    filings = submissions.get("filings", {})
    fold(filings.get("recent", {}))
    for page in filings.get("files", []):
        name = page.get("name")
        if name:
            fold(client.get_json(f"https://data.sec.gov/submissions/{name}"))
    return mapping


def fetch_filing_text(client: EdgarClient, cik: str, filing: dict) -> str:
    """Download the filing's primary document and strip it to plain text."""
    url = filing_document_url(cik, filing["accession_number"], filing["primary_document"])
    html = client.get_text(url)
    soup = BeautifulSoup(html, "lxml")
    for tag in soup(["script", "style"]):
        tag.decompose()
    text = soup.get_text(separator="\n")
    # Collapse blank-line runs left behind by table-heavy filing HTML
    lines = [line.strip() for line in text.splitlines()]
    return "\n".join(line for line in lines if line)
