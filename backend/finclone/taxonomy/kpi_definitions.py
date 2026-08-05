"""Industry-specific KPI definitions (PDR: Industry Taxonomy Engine).

Two sources of KPI targets, merged per company:

1. `gics_blueprint.BLUEPRINT` — 199 distinct KPIs across all 74 GICS industries,
   resolved from the company's SIC code via `gics_bridge`. This is the broad
   coverage layer, and the reason `kpis_for_company` exists: the sector table
   below matched only 28% of the universe, so 72% of companies were asked about
   the 3 GENERIC_KPIS alone.
2. `SECTOR_KPIS` — hand-curated entries for 9 coarse sectors. Kept because their
   keyword lists are richer than anything derived from a blueprint phrase
   (e.g. "dollar-based net" for net revenue retention). They take precedence
   when both sources name the same KPI.

`keywords` drive document-chunk selection (only chunks mentioning a keyword are
sent to the LLM); `label` is given to the LLM as an extraction target.
"""

import re

from finclone.taxonomy.gics_bridge import industry_for_company

# KPIs every company may report regardless of sector
GENERIC_KPIS: tuple[dict, ...] = (
    {"label": "Employee headcount", "keywords": ["employees", "headcount"]},
    {"label": "Backlog / remaining performance obligations",
     "keywords": ["backlog", "remaining performance obligation"]},
    {"label": "Share repurchases", "keywords": ["repurchase", "buyback"]},
)

SECTOR_KPIS: dict[str, tuple[dict, ...]] = {
    "Software & SaaS": (
        {"label": "Annual Recurring Revenue (ARR)", "keywords": ["annual recurring revenue", "ARR"]},
        {"label": "Net revenue retention", "keywords": ["net revenue retention", "net retention", "dollar-based net"]},
        {"label": "Customer count", "keywords": ["customers", "paid subscribers"]},
        {"label": "Billings", "keywords": ["billings"]},
    ),
    "Hospitality": (
        {"label": "RevPAR (revenue per available room)", "keywords": ["RevPAR", "revenue per available room"]},
        {"label": "ADR (average daily rate)", "keywords": ["average daily rate", "ADR"]},
        {"label": "Occupancy rate", "keywords": ["occupancy"]},
        {"label": "Room count", "keywords": ["rooms", "properties"]},
    ),
    "Semiconductors": (
        {"label": "Wafer capacity", "keywords": ["wafer", "capacity"]},
        {"label": "Fab utilization", "keywords": ["utilization", "fab"]},
        {"label": "Design wins", "keywords": ["design win"]},
    ),
    "Automotive": (
        {"label": "Vehicle deliveries", "keywords": ["deliveries", "delivered", "vehicles"]},
        {"label": "Vehicle production", "keywords": ["production", "produced", "manufactured"]},
        {"label": "Energy storage deployed", "keywords": ["energy storage", "deployed", "GWh", "MWh"]},
        {"label": "Regulatory credits revenue", "keywords": ["regulatory credits"]},
        {"label": "Charging / service locations", "keywords": ["Supercharger", "charging stations", "service centers"]},
    ),
    "Retail": (
        {"label": "Same-store / comparable sales growth", "keywords": ["comparable sales", "same-store", "comp sales"]},
        {"label": "Store count", "keywords": ["stores", "locations"]},
        {"label": "E-commerce revenue", "keywords": ["e-commerce", "online sales", "digital sales"]},
    ),
    "Banking": (
        {"label": "Net interest margin", "keywords": ["net interest margin"]},
        {"label": "Efficiency ratio", "keywords": ["efficiency ratio"]},
        {"label": "Non-performing loans", "keywords": ["non-performing", "nonperforming"]},
        {"label": "Tier 1 capital ratio", "keywords": ["tier 1", "CET1"]},
    ),
    "Oil & Gas": (
        {"label": "Production volume (BOE/d)", "keywords": ["barrels of oil equivalent", "boe", "production"]},
        {"label": "Proved reserves", "keywords": ["proved reserves"]},
        {"label": "Realized price per barrel", "keywords": ["realized price"]},
    ),
    "Media & Entertainment": (
        {"label": "Subscriber count", "keywords": ["subscribers", "memberships"]},
        {"label": "ARPU (average revenue per user)", "keywords": ["ARPU", "average revenue per"]},
        {"label": "Monthly/daily active users", "keywords": ["monthly active", "daily active", "MAU", "DAU"]},
    ),
    "Computer Hardware": (
        {"label": "Units shipped", "keywords": ["units", "shipments"]},
        {"label": "Installed base", "keywords": ["installed base", "active devices"]},
        {"label": "Services revenue", "keywords": ["services revenue"]},
    ),
}

# Analyst shorthand in the blueprint -> phrases that actually appear in filing
# prose. Without these, "AISC" or "RASM" as a chunk-selection keyword matches
# nothing: filings spell the term out, and often never use the acronym at all.
_ABBREVIATIONS: dict[str, tuple[str, ...]] = {
    # "ads", "sbc" and "tac" are below _MIN_KEYWORD_LEN, so without an entry
    # here they derive no keywords at all and get dropped from the target list.
    # test_gics_bridge.py asserts every blueprint phrase stays reachable.
    "ads": ("advertising revenue", "advertising"),
    "sbc": ("stock-based compensation", "share-based compensation"),
    "tac": ("traffic acquisition cost",),
    "adr": ("average daily rate",),
    "affo": ("adjusted funds from operations", "funds from operations"),
    "aisc": ("all-in sustaining cost", "sustaining cost"),
    "arpu": ("average revenue per user", "average revenue per"),
    "arr": ("annual recurring revenue",),
    "asm": ("available seat mile",),
    "asp": ("average selling price",),
    "aum": ("assets under management",),
    "bv": ("book value",),
    "casm": ("cost per available seat mile",),
    "cet1": ("common equity tier 1", "tier 1"),
    "cpc": ("cost per click",),
    "cpr": ("conditional prepayment rate", "prepayment"),
    "dau": ("daily active user",),
    "dtc": ("direct-to-consumer", "direct to consumer"),
    "fcf": ("free cash flow",),
    "gmv": ("gross merchandise value",),
    "loe": ("lease operating expense",),
    "mau": ("monthly active user",),
    "mcr": ("medical cost ratio", "medical loss ratio"),
    "mrr": ("monthly recurring revenue",),
    "ncos": ("net charge-off", "charge-off"),
    "nim": ("net interest margin",),
    "noi": ("net operating income",),
    "or": ("operating ratio",),
    "rasm": ("revenue per available seat mile",),
    "revpar": ("revenue per available room",),
    "roe": ("return on equity",),
    "rotce": ("return on tangible common equity",),
    "rpo": ("remaining performance obligation", "performance obligation"),
    "sss": ("same-store sales", "comparable sales"),
}

# Tokens too generic to discriminate between chunks of a filing — every page
# mentions them, so they'd pull in the whole document and defeat pre-filtering.
_TOKEN_STOPWORDS = frozenset({
    "and", "per", "the", "growth", "costs", "other", "total", "gross", "share",
    "rate", "rates", "ratio", "value", "count", "based",
})

# Substring matching means anything shorter than this produces false positives
# at scale ("OR" inside "for", "ARR" inside "arrangement"). Short acronyms are
# still reachable through _ABBREVIATIONS, which supplies the spelled-out phrase.
_MIN_KEYWORD_LEN = 4


def keywords_for_kpi(phrase: str) -> tuple[str, ...]:
    """Search keywords for one blueprint KPI phrase.

    The phrase itself is always kept; slash-separated alternates are split
    ("price/mix" -> "price", "mix"); acronyms are expanded via _ABBREVIATIONS;
    and individual words are added when long enough to match safely.
    """
    phrase = phrase.strip()
    if not phrase:
        return ()
    out: list[str] = []

    def add(candidate: str) -> None:
        candidate = candidate.strip().lower()
        if len(candidate) >= _MIN_KEYWORD_LEN and candidate not in out:
            out.append(candidate)

    add(phrase)
    for part in re.split(r"[/&]", phrase):
        add(part)
    for token in re.findall(r"[A-Za-z][A-Za-z0-9-]*", phrase):
        lowered = token.lower()
        for expansion in _ABBREVIATIONS.get(lowered, ()):
            add(expansion)
        if lowered not in _TOKEN_STOPWORDS and len(lowered) >= 5:
            add(lowered)
    return tuple(out)


def _blueprint_kpis(sic: str | None, sector: str | None) -> tuple[dict, ...]:
    """KPI targets from the company's GICS industry, or () if unresolvable."""
    industry = industry_for_company(sic, sector)
    if industry is None:
        return ()
    out: list[dict] = []
    for phrase in industry.key_kpis:
        keywords = keywords_for_kpi(phrase)
        if keywords:
            out.append({"label": phrase, "keywords": list(keywords)})
    return tuple(out)


def kpis_for_company(sic: str | None, sector: str | None) -> tuple[dict, ...]:
    """The KPI targets to extract for one company.

    Merge order — first writer of a label wins, so richer definitions survive:
    hand-curated sector entries, then the GICS blueprint, then the generic set.
    """
    merged: dict[str, dict] = {}
    for source in (SECTOR_KPIS.get(sector or "", ()),
                   _blueprint_kpis(sic, sector),
                   GENERIC_KPIS):
        for kpi in source:
            key = kpi["label"].strip().lower()
            if key not in merged:
                merged[key] = kpi
    return tuple(merged.values())


def kpis_for_sector(sector: str | None) -> tuple[dict, ...]:
    """Sector-only resolution. Retained for callers without a SIC code; prefer
    kpis_for_company, which reaches the blueprint's full 74-industry coverage."""
    return SECTOR_KPIS.get(sector or "", ()) + GENERIC_KPIS
