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


def test_no_anchor_company_products_in_kpi_phrases():
    """Blueprint KPI phrases become extraction targets and chunk-selection
    keywords for every company in the industry, so naming the anchor's own
    product asks Oracle about Azure and Walmart about AWS — a target that can
    never be extracted and a keyword that matches nothing."""
    vendor_products = ("azure", "aws", "iphone", "prime video", "windows",
                       "supercharger", "youtube", "instagram")
    offenders = [(b.number, b.gics_industry, phrase)
                 for b in BLUEPRINT for phrase in b.key_kpis
                 if any(p in phrase.lower() for p in vendor_products)]
    assert not offenders, f"anchor-specific KPI phrases: {offenders}"


def test_synonyms_across_sources_collapse_to_one_target():
    """SECTOR_KPIS and the blueprint name the same metric differently. Emitting
    both sends two extraction targets for one number and stores it under two
    labels, which splits any time series built from it."""
    cases = [
        ("7372", "Software & SaaS", {"annual recurring revenue (arr)", "arr"}),
        ("3711", "Automotive", {"vehicle deliveries", "deliveries"}),
        ("3711", "Automotive", {"vehicle production", "production"}),
        ("5812", "Retail",
         {"same-store / comparable sales growth", "same-store sales", "comp sales"}),
        ("5812", "Retail", {"store count", "units"}),
        ("1311", "Oil & Gas", {"proved reserves", "reserves"}),
        ("3571", "Computer Hardware", {"units shipped", "units"}),
        ("7812", "Media & Entertainment", {"subscriber count", "members"}),
    ]
    for sic, sector, group in cases:
        labels = [k["label"].lower() for k in kpis_for_company(sic, sector)]
        hits = [label for label in labels if label in group]
        assert len(hits) == 1, f"{sector}/{sic}: {group} emitted as {hits}"


def test_generic_kpis_collapse_into_blueprint_synonyms():
    """GENERIC_KPIS applies to every company, so its verbose labels collide
    with blueprint shorthand in industries no sector table covers."""
    labels = [k["label"].lower() for k in kpis_for_company("7372", "Software & SaaS")]
    assert sum(label in {"rpo", "backlog / remaining performance obligations"}
               for label in labels) == 1
    assert sum(label in {"employee headcount", "headcount"} for label in labels) == 1


def test_losing_synonym_contributes_its_keywords():
    """The point of merging rather than discarding: the dropped spelling is
    still how some filings word it, so it has to survive as a search keyword."""
    software = {k["label"]: k for k in kpis_for_company("7372", "Software & SaaS")}
    assert "backlog" in software["RPO"]["keywords"]      # from GENERIC_KPIS
    retail = {k["label"]: k for k in kpis_for_company("5812", "Retail")}
    assert "units" in retail["Store count"]["keywords"]  # from the blueprint


def test_returned_kpis_are_caller_owned_copies():
    """Callers get dicts they may mutate; the sources are module-level
    constants shared by every company in the sweep."""
    first = kpis_for_company("7372", "Software & SaaS")
    first[0]["keywords"].append("scribbled-on")
    second = kpis_for_company("7372", "Software & SaaS")
    assert "scribbled-on" not in second[0]["keywords"]


def test_sector_scoped_synonyms_do_not_leak_across_sectors():
    """"units" means store count for a restaurant chain and units shipped for a
    hardware maker — the reason the groups are keyed by sector at all."""
    from finclone.taxonomy.kpi_definitions import _merge_key
    assert _merge_key("units", "Retail") == _merge_key("store count", "Retail")
    assert _merge_key("units", "Computer Hardware") != _merge_key("store count",
                                                                 "Computer Hardware")
    assert _merge_key("units", None) == "units"
