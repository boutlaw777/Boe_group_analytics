"""Industry-specific KPI definitions (PDR: Industry Taxonomy Engine).

Each sector lists the niche, non-GAAP metrics its companies typically report
in MD&A/footnotes. The `keywords` drive document-chunk selection (only chunks
mentioning a keyword are sent to the LLM); the labels are given to the LLM as
extraction targets.
"""

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


def kpis_for_sector(sector: str | None) -> tuple[dict, ...]:
    return SECTOR_KPIS.get(sector or "", ()) + GENERIC_KPIS
