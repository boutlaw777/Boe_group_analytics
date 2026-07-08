from finclone.pipeline.normalize import (
    classify_tag,
    is_annual_duration,
    is_quarterly_duration,
)
from finclone.taxonomy.sic_map import sector_for_sic


def test_classify_known_tag():
    name, priority, is_flow = classify_tag("Revenues")
    assert name == "revenue"
    assert priority > 0  # not the preferred tag
    assert is_flow


def test_classify_preferred_tag_has_priority_zero():
    name, priority, _ = classify_tag("RevenueFromContractWithCustomerExcludingAssessedTax")
    assert name == "revenue"
    assert priority == 0


def test_classify_unknown_tag():
    assert classify_tag("SomeObscureTag") is None


def test_quarterly_duration_detection():
    assert is_quarterly_duration("2023-07-01", "2023-09-30")
    assert not is_quarterly_duration("2023-01-01", "2023-09-30")  # 9-month YTD
    assert not is_quarterly_duration(None, "2023-09-30")  # instant


def test_annual_duration_detection():
    assert is_annual_duration("2023-01-01", "2023-12-31")
    assert not is_annual_duration("2023-07-01", "2023-09-30")


def test_sic_narrowest_range_wins():
    assert sector_for_sic("7372") == "Software & SaaS"  # not IT Services / Manufacturing
    assert sector_for_sic("3674") == "Semiconductors"
    assert sector_for_sic("6798") == "REITs"


def test_sic_edge_cases():
    assert sector_for_sic(None) is None
    assert sector_for_sic("not-a-code") is None
    assert sector_for_sic("9999") == "Other"
