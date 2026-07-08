from finclone.pipeline.monitor import _recent_filings


def test_recent_filings_filters_watched_forms():
    submissions = {
        "filings": {
            "recent": {
                "form": ["10-Q", "4", "8-K", "S-8", "10-K"],
                "accessionNumber": ["a1", "a2", "a3", "a4", "a5"],
                "filingDate": ["2026-05-01", "2026-04-20", "2026-04-15", "2026-03-01", "2025-11-01"],
            }
        }
    }
    filings = _recent_filings(submissions)
    assert [f["form"] for f in filings] == ["10-Q", "8-K", "10-K"]
    assert filings[0]["accession_number"] == "a1"


def test_recent_filings_empty_submissions():
    assert _recent_filings({}) == []
    assert _recent_filings({"filings": {"recent": {}}}) == []
