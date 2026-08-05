"""SIC -> GICS bridge and the KPI targets derived from it."""

import pytest

from finclone.taxonomy import gics_bridge
from finclone.taxonomy.gics_blueprint import BLUEPRINT
from finclone.taxonomy.kpi_definitions import (
    GENERIC_KPIS,
    keywords_for_kpi,
    kpis_for_company,
    kpis_for_sector,
)


def test_every_mapped_industry_number_exists():
    """A typo'd number in _SIC_TO_GICS would resolve to None at runtime and
    silently downgrade those companies to generic KPIs, with no error."""
    valid = {b.number for b in BLUEPRINT}
    referenced = {number for _, _, number in gics_bridge._SIC_TO_GICS}
    assert referenced <= valid, f"unknown industry numbers: {sorted(referenced - valid)}"


def test_every_sector_fallback_number_exists():
    valid = {b.number for b in BLUEPRINT}
    referenced = set(gics_bridge._SECTOR_TO_GICS.values())
    assert referenced <= valid, f"unknown industry numbers: {sorted(referenced - valid)}"


def test_sic_ranges_are_well_formed():
    for lo, hi, _ in gics_bridge._SIC_TO_GICS:
        assert lo <= hi, f"inverted range {lo}-{hi}"


@pytest.mark.parametrize("sic,expected", [
    ("3674", "Semiconductors & Semiconductor Equipment"),
    ("2836", "Biotechnology"),
    ("2834", "Pharmaceuticals"),
    ("6022", "Banks"),
    ("7372", "Software"),
    ("7374", "IT Services"),
    ("4512", "Passenger Airlines"),
    ("1311", "Oil, Gas & Consumable Fuels"),
    ("1381", "Energy Equipment & Services"),
    ("6798", "Diversified REITs"),
    ("3711", "Automobiles"),
    ("4911", "Electric Utilities"),
    ("5812", "Hotels, Restaurants & Leisure"),
])
def test_sic_spot_checks(sic, expected):
    industry = gics_bridge.industry_for_sic(sic)
    assert industry is not None and industry.gics_industry == expected


def test_narrowest_range_wins():
    """3674 sits inside 3670-3679 (electronic components) and 3600-3699
    (electrical equipment); the exact match must win."""
    assert gics_bridge.industry_for_sic("3674").gics_industry.startswith("Semiconductors")
    assert gics_bridge.industry_for_sic("3672").gics_industry.startswith("Electronic Equipment")


def test_unusable_sic_returns_none():
    for value in (None, "", "   ", "abcd", "9999"):
        assert gics_bridge.industry_for_sic(value) is None


def test_sector_fallback_used_when_sic_missing():
    assert gics_bridge.industry_for_company(None, "Banking").gics_industry == "Banks"
    assert gics_bridge.industry_for_company("abcd", "Hospitality").number == 27


def test_ambiguous_sectors_are_not_guessed():
    """"Manufacturing" spans a dozen GICS industries — attaching one industry's
    KPIs would be confidently wrong, so it must stay unresolved."""
    for sector in ("Manufacturing", "Other", "Wholesale"):
        assert gics_bridge.industry_for_sector(sector) is None


def test_sic_beats_sector_when_both_present():
    # SIC 3674 is a semiconductor maker even though sic_map's coarse sector for
    # it would be the broader electronics bucket.
    assert gics_bridge.industry_for_company("3674", "Banking").number == 55


# --- keyword derivation ---------------------------------------------------

def test_short_tokens_never_become_keywords():
    """Chunk selection is substring matching, so "or" would match "for" on
    every page and defeat pre-filtering entirely."""
    for phrase in ("OR", "BV", "ASP", "FCF", "NIM"):
        assert all(len(k) >= 4 for k in keywords_for_kpi(phrase))
        assert "or" not in keywords_for_kpi(phrase)


def test_abbreviations_expand_to_filing_prose():
    assert "all-in sustaining cost" in keywords_for_kpi("AISC")
    assert "revenue per available room" in keywords_for_kpi("RevPAR")
    assert "operating ratio" in keywords_for_kpi("OR")
    assert "net charge-off" in keywords_for_kpi("NCOs")


def test_slash_alternates_are_split():
    assert "price" in keywords_for_kpi("price/mix")


def test_empty_phrase_yields_nothing():
    assert keywords_for_kpi("") == ()
    assert keywords_for_kpi("   ") == ()


# --- merged KPI targets ---------------------------------------------------

def test_generic_kpis_always_present():
    generic = {k["label"] for k in GENERIC_KPIS}
    for sic, sector in [("3674", "Semiconductors"), ("9999", "Other"), (None, None)]:
        labels = {k["label"] for k in kpis_for_company(sic, sector)}
        assert generic <= labels


def test_blueprint_extends_a_curated_sector():
    """Semiconductors is hand-curated AND mapped to a GICS industry; the result
    must be the union, not one replacing the other."""
    labels = {k["label"] for k in kpis_for_company("3674", "Semiconductors")}
    assert "Wafer capacity" in labels          # from SECTOR_KPIS
    assert "ASP" in labels                     # from the blueprint
    assert len(labels) > len(kpis_for_sector("Semiconductors"))


def test_curated_definition_wins_on_label_collision():
    """SECTOR_KPIS keywords are richer than anything derived from a phrase, so
    on a duplicate label the curated entry must survive."""
    banking = {k["label"]: k for k in kpis_for_company("6022", "Banking")}
    assert banking["Net interest margin"]["keywords"] == ["net interest margin"]


def test_previously_unmapped_sector_now_gets_industry_kpis():
    """The whole point of the bridge: a pharma company used to fall through to
    the 3 generic KPIs because "Pharmaceuticals & Biotech" has no SECTOR_KPIS
    entry."""
    labels = {k["label"] for k in kpis_for_company("2834", "Pharmaceuticals & Biotech")}
    assert len(labels) > len(GENERIC_KPIS)


def test_every_returned_kpi_has_usable_keywords():
    for b in BLUEPRINT:
        for kpi in kpis_for_company(None, None) + tuple(
                {"label": p, "keywords": list(keywords_for_kpi(p))} for p in b.key_kpis):
            assert kpi["keywords"], f"{kpi['label']} produced no keywords"


def test_one_spelling_per_kpi_across_the_blueprint():
    """The source PDF spells 14 KPIs inconsistently between industries
    ("Volume" in five rows, "volume" in four). Handing each industry its own
    casing stores one metric under two names — the duplicate-name bug
    ('Share repurchases' vs 'share repurchases') arriving from another
    direction, and invisible until the sweep reaches both industries."""
    from finclone.taxonomy.kpi_definitions import _blueprint_kpis

    emitted: dict[str, set[str]] = {}
    for b in BLUEPRINT:
        for kpi in _blueprint_kpis(None, b.sector):
            emitted.setdefault(kpi["label"].lower(), set()).add(kpi["label"])
    collisions = {k: sorted(v) for k, v in emitted.items() if len(v) > 1}
    assert not collisions, f"KPI emitted under multiple spellings: {collisions}"


def test_canonical_choice_is_deterministic():
    """Lowest industry number wins, so the stored spelling doesn't depend on
    which company happens to be processed first."""
    from finclone.taxonomy.kpi_definitions import _canonical_blueprint_labels
    assert _canonical_blueprint_labels() == _canonical_blueprint_labels()
