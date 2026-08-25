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

from finclone.taxonomy.gics_blueprint import BLUEPRINT
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

# The same metric under two names, once per source. `kpis_for_company` merges
# SECTOR_KPIS with the blueprint, deduplicating on the label — which catches
# "Backlog" vs "backlog" but not "Annual Recurring Revenue (ARR)" vs "ARR".
# Both then reach the LLM as separate extraction targets and get stored as two
# KPI rows for one metric, so a chart of ARR over time silently splits in half.
#
# Groups list every spelling of one metric; the first source to name any member
# wins the label (hand-curated beats blueprint, per the merge order), and the
# losers' keywords fold into it rather than being dropped.
#
# Sector-scoped because the shorthand is not globally unambiguous: "units" means
# store count for a restaurant chain and units shipped for a hardware maker.
# Only _GLOBAL_SYNONYMS below may be applied without knowing the sector.
_SECTOR_SYNONYMS: dict[str, tuple[frozenset[str], ...]] = {
    "Oil & Gas": (
        frozenset({"production volume (boe/d)", "production"}),
        frozenset({"proved reserves", "reserves"}),
        frozenset({"realized price per barrel", "realized price"}),
    ),
    "Automotive": (
        frozenset({"vehicle deliveries", "deliveries"}),
        frozenset({"vehicle production", "production"}),
    ),
    "Retail": (
        frozenset({"same-store / comparable sales growth", "same-store sales",
                   "comp sales"}),
        frozenset({"store count", "units"}),
        frozenset({"e-commerce revenue", "e-commerce"}),
    ),
    "Banking": (
        frozenset({"net interest margin", "nim"}),
        # CET1 is a stricter cut of Tier 1, but SECTOR_KPIS already searches for
        # both under one label, so splitting them here would contradict it.
        frozenset({"tier 1 capital ratio", "cet1"}),
    ),
    "Software & SaaS": (
        frozenset({"annual recurring revenue (arr)", "arr"}),
    ),
    "Media & Entertainment": (
        frozenset({"subscriber count", "members"}),
        frozenset({"arpu (average revenue per user)", "arpu"}),
    ),
    "Computer Hardware": (
        frozenset({"units shipped", "units"}),
    ),
}

# Safe in any sector: these mean the same thing across the whole universe.
# GENERIC_KPIS applies to every company, so its labels collide with blueprint
# phrases in industries no sector table covers.
_GLOBAL_SYNONYMS: tuple[frozenset[str], ...] = (
    frozenset({"backlog / remaining performance obligations", "backlog", "rpo"}),
    frozenset({"employee headcount", "headcount"}),
)


def _merge_key(label: str, sector: str | None) -> str:
    """Dedupe key for one KPI label: the metric it names, not its spelling."""
    lowered = label.strip().lower()
    for group in _SECTOR_SYNONYMS.get(sector or "", ()) + _GLOBAL_SYNONYMS:
        if lowered in group:
            return min(group)  # any stable member; independent of merge order
    return lowered


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


def _canonical_blueprint_labels() -> dict[str, str]:
    """One spelling per KPI across the whole blueprint, keyed by lowercase.

    The blueprint mirrors the source PDF faithfully, and the PDF spells some
    KPIs inconsistently between industries — "Volume" in five rows, "volume" in
    four. Offering each industry its own casing stores the same metric under two
    names, which is the duplicate-name bug (`Share repurchases` vs `share
    repurchases`) reappearing from a different direction. Lowest industry number
    wins, so the choice is stable rather than dependent on lookup order.
    """
    canonical: dict[str, str] = {}
    for industry in sorted(BLUEPRINT, key=lambda b: b.number):
        for phrase in industry.key_kpis:
            canonical.setdefault(phrase.strip().lower(), phrase.strip())
    return canonical


_CANONICAL_LABELS = _canonical_blueprint_labels()


def _blueprint_kpis(sic: str | None, sector: str | None) -> tuple[dict, ...]:
    """KPI targets from the company's GICS industry, or () if unresolvable."""
    industry = industry_for_company(sic, sector)
    if industry is None:
        return ()
    out: list[dict] = []
    for phrase in industry.key_kpis:
        keywords = keywords_for_kpi(phrase)
        if keywords:
            label = _CANONICAL_LABELS.get(phrase.strip().lower(), phrase.strip())
            out.append({"label": label, "keywords": list(keywords)})
    return tuple(out)


def kpis_for_company(sic: str | None, sector: str | None) -> tuple[dict, ...]:
    """The KPI targets to extract for one company.

    Merge order — first writer of a metric wins the label, so richer definitions
    survive: hand-curated sector entries, then the GICS blueprint, then the
    generic set. Later sources naming the same metric under a different spelling
    (see _SECTOR_SYNONYMS) contribute their keywords to the winning entry
    instead of adding a second target for the same number.

    Entries are copies: the returned dicts are callers' to mutate, and the
    sources are module-level constants shared by every company.
    """
    merged: dict[str, dict] = {}
    for source in (SECTOR_KPIS.get(sector or "", ()),
                   _blueprint_kpis(sic, sector),
                   GENERIC_KPIS):
        for kpi in source:
            key = _merge_key(kpi["label"], sector)
            existing = merged.get(key)
            if existing is None:
                merged[key] = {"label": kpi["label"], "keywords": list(kpi["keywords"])}
                continue
            seen = {k.lower() for k in existing["keywords"]}
            for keyword in kpi["keywords"]:
                if keyword.lower() not in seen:
                    existing["keywords"].append(keyword)
                    seen.add(keyword.lower())
    return tuple(merged.values())


def kpis_for_sector(sector: str | None) -> tuple[dict, ...]:
    """Sector-only resolution. Retained for callers without a SIC code; prefer
    kpis_for_company, which reaches the blueprint's full 74-industry coverage."""
    return SECTOR_KPIS.get(sector or "", ()) + GENERIC_KPIS


# --- canonical KPI names -------------------------------------------------
#
# The extraction prompt asks for "canonical KPI name from the target list" and
# the sweep maps the answer back with an exact lowercase lookup — which catches
# the model echoing "share repurchases" for "Share repurchases" and nothing
# else. Every rewording lands in the database as a new metric: one hotel's
# RevPAR is stored under "RevPAR", the next under "Revenue per available room",
# and Data Point Search (a substring match on the name) finds one but not the
# other. Comparing a KPI across an industry is the entire point of extracting
# it, so the stored name has to be the industry's name for it, not the wording
# that happened to appear in one filing's MD&A.
#
# Matching is deliberately generous but never guesses: variants are derived the
# same way on both sides so they meet in the middle, and any variant two target
# labels both claim is dropped rather than resolved to one of them.

_PAREN = re.compile(r"\(([^)]*)\)")
_NON_ALNUM = re.compile(r"[^a-z0-9 ]+")

# Words that distinguish no metric. "Occupancy" and "Occupancy rate" are one
# KPI; keeping both splits one series in two.
_NAME_FILLER = frozenset({
    "rate", "ratio", "total", "count", "number", "amount", "level", "growth",
    "per", "of", "the", "and", "in",
})


def _flatten(text: str) -> str:
    """Whitespace- and punctuation-insensitive form of one name fragment."""
    return " ".join(_NON_ALNUM.sub(" ", text).split())


def _name_variants(name: str) -> frozenset[str]:
    """Every spelling that should resolve to the same KPI as `name`."""
    raw = name.strip().lower().replace("\u2013", "-").replace("\u2014", "-")
    if not raw:
        return frozenset()

    # Surface forms: the whole string, its parenthetical gloss, the string
    # without that gloss, and each slash-separated alternate. This is what
    # bridges "RevPAR" and "revenue per available room" — the target label
    # carries both, so either wording finds it.
    seeds = {raw, _PAREN.sub(" ", raw)}
    seeds.update(inner for inner in _PAREN.findall(raw))
    seeds.update(part for seed in tuple(seeds) for part in seed.split("/"))

    out: set[str] = set()
    for seed in seeds:
        tokens = _flatten(seed).split()
        if not tokens:
            continue
        expanded = [word for token in tokens
                    for word in (_ABBREVIATIONS[token][0].split()
                                 if token in _ABBREVIATIONS else [token])]
        for form in (tokens, expanded):
            out.add(" ".join(form))
            # Filler-stripped, then de-pluralized: "Design wins" == "design win",
            # "Occupancy rate" == "occupancy". Guarded on length so "billings"
            # and "seats" don't lose meaning.
            trimmed = [t for t in form if t not in _NAME_FILLER] or list(form)
            out.add(" ".join(trimmed))
            out.add(" ".join(t[:-1] if len(t) > 4 and t.endswith("s") else t
                             for t in trimmed))
    return frozenset(v for v in out if v)


def canonical_name_index(labels: tuple[str, ...] | list[str]) -> dict[str, str]:
    """Map every recognizable spelling to the target label it belongs to.

    Two tiers. A label's own flattened form always resolves to itself — those
    are distinct by construction, so they can never be ambiguous. Derived
    variants sit underneath and are discarded when two labels both produce one:
    silently filing a hotel's occupancy under another industry's metric is worse
    than leaving the model's wording alone for a human to notice.
    """
    exact: dict[str, str] = {}
    for label in labels:
        key = _flatten(label.strip().lower())
        if key:
            exact.setdefault(key, label)

    derived: dict[str, str] = {}
    contested: set[str] = set()
    for label in labels:
        for variant in _name_variants(label):
            if variant in exact:
                continue
            if derived.setdefault(variant, label) != label:
                contested.add(variant)
    for variant in contested:
        derived.pop(variant, None)

    return {**derived, **exact}


def resolve_kpi_name(stated: str, index: dict[str, str]) -> str | None:
    """The target label `stated` names, or None if it names none of them.

    None is a real answer, not a failure: the model does surface genuine KPIs
    nobody listed, and those are worth keeping under the model's own wording.
    The caller decides — this only reports whether the name is one we asked for.
    """
    variants = _name_variants(stated)
    exact = _flatten(stated.strip().lower())
    if exact in index:
        return index[exact]
    # Longest first: the least-normalized match is the most specific one.
    for variant in sorted(variants, key=lambda v: (-len(v), v)):
        if variant in index:
            return index[variant]
    return None
