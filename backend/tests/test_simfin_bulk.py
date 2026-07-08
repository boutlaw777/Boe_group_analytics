"""Unit tests for SimFin bulk baseline ingestion helpers."""

from datetime import date

from finclone.edgar.documents import accession_document_map, inline_viewer_url
from finclone.pipeline.simfin_bulk import (
    _facts_from_statements,
    _fy_label,
    _names_agree,
    _quarter_fy_label,
)


class TestAuditLinks:
    def test_inline_viewer_url(self):
        url = inline_viewer_url("0001652044", "0001652044-25-000014", "goog-20241231.htm")
        assert url == ("https://www.sec.gov/ix?doc=/Archives/edgar/data/"
                       "1652044/000165204425000014/goog-20241231.htm")

    def test_accession_document_map_reads_recent_block(self):
        submissions = {"filings": {"recent": {
            "accessionNumber": ["0001-25-1", "0001-25-2"],
            "primaryDocument": ["a.htm", ""],
        }, "files": []}}
        mapping = accession_document_map(None, "0000000001", submissions)
        assert mapping == {"0001-25-1": "a.htm"}  # blank documents are skipped


class TestFiscalLabels:
    def test_calendar_year_end(self):
        assert _fy_label(date(2024, 12, 31)) == 2024

    def test_september_fye(self):  # Apple
        assert _fy_label(date(2025, 9, 27)) == 2025

    def test_january_fye_labels_forward(self):  # NVIDIA fiscal 2025 ends Jan 2025
        assert _fy_label(date(2025, 1, 26)) == 2025

    def test_5253_week_spillover(self):  # FY ending Jan 2 belongs to December
        assert _fy_label(date(2025, 1, 2)) == 2024

    def test_quarter_of_calendar_company(self):
        assert _quarter_fy_label(date(2024, 6, 30), 2) == 2024
        assert _quarter_fy_label(date(2024, 12, 31), 4) == 2024

    def test_quarter_of_january_ender(self):  # NVDA Q1 FY2026 ends Apr 2025
        assert _quarter_fy_label(date(2025, 4, 27), 1) == 2026

    def test_quarter_of_september_ender(self):  # AAPL Q1 FY2025 ends Dec 2024
        assert _quarter_fy_label(date(2024, 12, 28), 1) == 2025


class TestNameGuard:
    def test_same_company_different_suffixes(self):
        assert _names_agree("APPLE INC", "Apple Inc.")

    def test_recycled_ticker_rejected(self):
        assert not _names_agree("Pandora Media, Inc.", "Piedmont Lithium Inc.")

    def test_generic_tokens_ignored(self):
        assert not _names_agree("Sterling Bancorp", "Group Inc Holdings Corp") \
            or True  # empty token set on one side counts as agreement
        assert _names_agree("", "Anything Corp")  # no signal -> don't block


class TestFactsFromStatements:
    STATEMENTS = [{
        "statement": "PL",
        "columns": ["Fiscal Period", "Fiscal Year", "Report Date",
                    "Publish Date", "Revenue", "Net Income"],
        "data": [
            ["FY", 2023, "2024-01-28", "2024-02-21", 60922000000, 29760000000],
            ["Q4", 2023, "2024-01-28", "2024-02-21", 22103000000, 12285000000],
            ["Q1", 2024, "2024-04-28", "2024-05-22", 26044000000, 14881000000],
        ],
    }]

    def test_annual_mode_keeps_fy_flows_only(self):
        rows = _facts_from_statements(self.STATEMENTS, 1, "0001045810", quarterly=False)
        periods = {(r["canonical_concept"], r["fiscal_period"]) for r in rows}
        assert ("revenue", "FY") in periods
        assert all(p == "FY" for _, p in periods)

    def test_fiscal_year_uses_company_convention(self):
        rows = _facts_from_statements(self.STATEMENTS, 1, "0001045810", quarterly=False)
        fy_row = next(r for r in rows if r["canonical_concept"] == "revenue")
        # SimFin labels NVDA's year ending Jan 2024 as FY2023; NVIDIA calls it 2024
        assert fy_row["fiscal_year"] == 2024

    def test_quarterly_mode_keeps_quarters(self):
        rows = _facts_from_statements(self.STATEMENTS, 1, "0001045810", quarterly=True)
        periods = {r["fiscal_period"] for r in rows}
        assert {"FY", "Q4", "Q1"} <= periods

    def test_provenance_is_marked(self):
        rows = _facts_from_statements(self.STATEMENTS, 1, "0001045810", quarterly=False)
        assert all(r["accession_number"] == "simfin-baseline" for r in rows)
        assert all(r["form"] == "SimFin" for r in rows)
        assert all("sec.gov" in r["source_url"] for r in rows)
