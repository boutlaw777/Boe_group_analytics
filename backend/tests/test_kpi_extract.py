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
