import pytest

from finclone.pipeline.kpi_extract import _select_chunks
from finclone.taxonomy.kpi_definitions import GENERIC_KPIS, kpis_for_sector


def test_sector_kpis_include_generics():
    kpis = kpis_for_sector("Hospitality")
    labels = [k["label"] for k in kpis]
    assert any("RevPAR" in label for label in labels)
    assert any("headcount" in label.lower() for label in labels)


def test_unknown_sector_falls_back_to_generics():
    assert kpis_for_sector(None) == GENERIC_KPIS
    assert kpis_for_sector("Nonexistent Sector") == GENERIC_KPIS


def test_chunk_selection_prefers_keyword_dense_sections():
    filler = "irrelevant text about nothing in particular. " * 400
    relevant = "RevPAR increased 5% to $120. Occupancy was 72%. RevPAR growth continued. " * 50
    text = filler + relevant + filler
    chunks = _select_chunks(text, ["RevPAR", "occupancy"], max_chunks=2)
    assert chunks
    assert all("RevPAR" in c for c in chunks)


def test_chunk_selection_empty_when_no_keywords_match():
    assert _select_chunks("nothing relevant here " * 1000, ["RevPAR"], max_chunks=3) == []


# --- a single unresolvable ticker must not kill the sweep -------------------

def test_not_ingested_is_a_recoverable_exception():
    """It used to raise SystemExit, which inherits from BaseException, so the
    sweep's `except Exception` never caught it: one bad ticker aborted the whole
    --all run and the supervisor misreported the exit as a provider quota,
    retrying the same ticker hourly forever. Coverage stalled at 521/3,010."""
    from finclone.pipeline.kpi_extract import _NotIngested
    assert issubclass(_NotIngested, Exception)
    assert not issubclass(_NotIngested, SystemExit)
    # and it must be catchable by the sweep's generic handler
    try:
        raise _NotIngested("CLBK")
    except Exception as e:
        assert str(e) == "CLBK"


# --- KPI name standardization (QA review Aug 2026, Analytics #4) ----------


def _hotel_index():
    from finclone.taxonomy.kpi_definitions import canonical_name_index, kpis_for_company
    return canonical_name_index(
        [k["label"] for k in kpis_for_company("7011", "Hospitality")])


@pytest.mark.parametrize("stated,expected", [
    ("RevPAR", "RevPAR (revenue per available room)"),
    ("revpar", "RevPAR (revenue per available room)"),
    ("Revenue per available room", "RevPAR (revenue per available room)"),
    ("RevPAR (revenue per available room)", "RevPAR (revenue per available room)"),
    ("ADR", "ADR (average daily rate)"),
    ("Average daily rate", "ADR (average daily rate)"),
    ("Occupancy", "Occupancy rate"),
    ("Occupancy rate", "Occupancy rate"),
    ("Rooms", "Room count"),
])
def test_model_wording_resolves_to_the_industry_name(stated, expected):
    """The model rewords the target label as often as it echoes it. Each
    wording below is one metric; storing them separately is what stopped a KPI
    being comparable across an industry."""
    from finclone.taxonomy.kpi_definitions import resolve_kpi_name
    assert resolve_kpi_name(stated, _hotel_index()) == expected


def test_unlisted_kpi_is_not_forced_onto_a_target():
    """The model does surface genuine KPIs nobody listed. Those must come back
    as None so the caller keeps the model's wording — Data Point Search exists
    to find exactly these — rather than being filed under the nearest label."""
    from finclone.taxonomy.kpi_definitions import resolve_kpi_name
    index = _hotel_index()
    assert resolve_kpi_name("Loyalty program members", index) is None
    assert resolve_kpi_name("Pipeline of signed hotels", index) is None


def test_every_target_label_resolves_to_itself():
    """Idempotence across every label set the taxonomy can produce: if a label
    resolved to a different one, extraction would rename correct output."""
    from finclone.taxonomy.gics_bridge import industry_for_sic
    from finclone.taxonomy.kpi_definitions import (
        canonical_name_index, kpis_for_company, resolve_kpi_name)
    from finclone.taxonomy.sic_map import sector_for_sic

    checked = 0
    for number in range(100, 10000):
        sic = str(number).zfill(4)
        if industry_for_sic(number) is None:
            continue
        sector = sector_for_sic(sic)
        labels = [k["label"] for k in kpis_for_company(sic, sector)]
        index = canonical_name_index(labels)
        for label in labels:
            assert resolve_kpi_name(label, index) == label, f"{sic}: {label}"
        checked += 1
    assert checked > 1000


def test_variant_claimed_by_two_labels_is_dropped_not_guessed():
    """Same principle as the sector bridge refusing to guess: filing one
    industry's metric under another's name is worse than leaving it alone."""
    from finclone.taxonomy.kpi_definitions import canonical_name_index, resolve_kpi_name
    index = canonical_name_index(["Store count", "Room count"])
    assert resolve_kpi_name("Store count", index) == "Store count"
    assert resolve_kpi_name("Room count", index) == "Room count"
    assert resolve_kpi_name("Count", index) is None


@pytest.mark.parametrize("stated,expected", [
    ("Q3 2025", "Q3 FY2025"),
    ("Q3 FY2025", "Q3 FY2025"),
    ("q3 fy 2025", "Q3 FY2025"),
    ("H1 2025", "H1 FY2025"),
    ("FY2025", "FY2025"),
    ("fiscal year 2025", "FY2025"),
    ("full year 2025", "FY2025"),
    ("2025", "FY2025"),
    ("2025-09-27", "as of 2025-09-27"),
    ("as of 2025-09-27", "as of 2025-09-27"),
])
def test_period_spellings_collapse_to_one_form(stated, expected):
    """KpiFact is unique on (company, name, period, accession), so an
    unnormalized period doesn't collide with its twin — it stores the same
    datapoint twice and splits the time series."""
    from finclone.pipeline.kpi_extract import normalize_period
    assert normalize_period(stated) == expected


def test_unparseable_period_is_left_in_the_models_words():
    from finclone.pipeline.kpi_extract import normalize_period
    assert normalize_period("fiscal 2025 second quarter") == "fiscal 2025 second quarter"
    assert normalize_period("  trailing twelve months  ") == "trailing twelve months"


@pytest.mark.parametrize("stated,expected", [
    ("$", "USD"), ("USD", "USD"), ("dollars", "USD"), ("US Dollars", "USD"),
    ("%", "percent"), ("percent", "percent"), ("Percentage", "percent"),
    ("rooms", "rooms"), ("GWh", "GWh"), ("", ""),
])
def test_unit_spellings_collapse_to_one_form(stated, expected):
    from finclone.pipeline.kpi_extract import normalize_unit
    assert normalize_unit(stated) == expected


def test_extraction_prompt_asks_for_one_period_format():
    """The rules block demanded a canonical period while the response-shape
    example illustrated the format it forbids, so the model was told both."""
    from finclone.pipeline.kpi_extract import _SYSTEM
    assert "Q3 2025" not in _SYSTEM
    assert "Q<n> FY<yyyy>" in _SYSTEM
