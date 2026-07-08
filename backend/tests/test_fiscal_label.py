from datetime import date

from finclone.pipeline.ingest import _fiscal_label


def test_apple_september_fye():
    # Apple: FYE September. FY2016 runs Sep 2015 -> Sep 2016.
    assert _fiscal_label(date(2015, 12, 26), 9) == (2016, 1)  # Q1 ends Dec
    assert _fiscal_label(date(2016, 3, 26), 9) == (2016, 2)
    assert _fiscal_label(date(2016, 6, 25), 9) == (2016, 3)
    assert _fiscal_label(date(2016, 9, 24), 9) == (2016, 4)


def test_52_53_week_spillover():
    # A September FYE landing on Oct 1 still belongs to the Sep fiscal year
    assert _fiscal_label(date(2016, 10, 1), 9) == (2016, 4)
    # ...but a genuine late-October date belongs to the next fiscal year's Q1 window
    assert _fiscal_label(date(2016, 10, 29), 9)[0] == 2017


def test_nvidia_january_fye():
    # NVDA: FYE late January; fiscal year labeled by ending calendar year.
    assert _fiscal_label(date(2024, 1, 28), 1) == (2024, 4)   # FY2024 year end
    assert _fiscal_label(date(2023, 4, 30), 1) == (2024, 1)   # Q1 FY2024
    assert _fiscal_label(date(2023, 10, 29), 1) == (2024, 3)  # Q3 FY2024
    # Feb 1 spillover still counts as the January year end
    assert _fiscal_label(date(2024, 2, 1), 1) == (2024, 4)


def test_calendar_year_companies():
    # Amazon/Google: FYE December — fiscal periods match calendar quarters.
    assert _fiscal_label(date(2024, 3, 31), 12) == (2024, 1)
    assert _fiscal_label(date(2024, 12, 31), 12) == (2024, 4)


def test_microsoft_june_fye():
    assert _fiscal_label(date(2016, 6, 30), 6) == (2016, 4)   # FY2016 year end
    assert _fiscal_label(date(2015, 9, 30), 6) == (2016, 1)   # Q1 FY2016
