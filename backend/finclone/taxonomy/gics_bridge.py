"""SIC code → GICS industry bridge (M5 → M4 wiring).

`gics_blueprint.py` encodes all 74 GICS industries with their key operating
KPIs, but nothing consumed it: KPI extraction ran off `kpi_definitions.py`,
whose 9 hand-curated sectors matched only 28% of the company universe (the
other 72% fell through to the 3 GENERIC_KPIS). This module is the missing join.

SEC filings carry a SIC code, not a GICS industry, and there is no official
crosswalk between the two — SIC is a 1987-era US government taxonomy, GICS is
MSCI's. The map below is a pragmatic best-fit at the SIC major-group level,
chosen so every company lands on the industry whose KPI set an analyst would
actually reach for. It is deliberately coarser than GICS sub-industries: a
mis-assignment inside the right sector still yields mostly-relevant KPIs, so
breadth beats precision here.

Narrowest matching range wins, same convention as `sic_map.sector_for_sic` —
so 3674 (semiconductors) beats the 3600-3699 electronics range that contains it.
"""

from finclone.taxonomy.gics_blueprint import BLUEPRINT, IndustryBlueprint

# (sic_low, sic_high, gics_industry_number). Ranges may overlap; the narrowest
# match wins. Numbers refer to IndustryBlueprint.number in gics_blueprint.py.
_SIC_TO_GICS: tuple[tuple[int, int, int], ...] = (
    # --- Agriculture / extractive ---
    (100, 999, 34),      # Agriculture -> Food Products
    (800, 899, 7),       # Forestry -> Paper & Forest Products
    (1000, 1099, 6),     # Metal mining -> Metals & Mining
    (1200, 1299, 2),     # Coal -> Oil, Gas & Consumable Fuels
    (1300, 1399, 2),     # Oil & gas extraction
    (1381, 1389, 1),     # Oil & gas field services -> Energy Equipment & Services
    (1400, 1499, 4),     # Nonmetallic minerals -> Construction Materials
    # --- Construction ---
    (1500, 1799, 10),    # Construction -> Construction & Engineering
    (1520, 1531, 24),    # Homebuilders -> Household Durables
    # --- Food, beverage, tobacco ---
    (2000, 2099, 34),    # Food
    (2080, 2086, 33),    # Beverages
    (2100, 2199, 35),    # Tobacco
    # --- Textiles / apparel ---
    (2200, 2399, 26),    # Textiles & apparel
    (3100, 3199, 26),    # Leather & footwear
    # --- Paper, packaging, print ---
    (2400, 2499, 7),     # Lumber & wood
    (2500, 2599, 24),    # Furniture & fixtures -> Household Durables
    (2600, 2699, 7),     # Paper
    (2650, 2659, 5),     # Containers -> Containers & Packaging
    (3220, 3221, 5),     # Glass containers
    (2700, 2799, 58),    # Printing & publishing -> Media
    # --- Chemicals & pharma ---
    (2800, 2899, 3),     # Chemicals
    (2833, 2834, 42),    # Pharmaceutical preparations -> Pharmaceuticals
    (2835, 2835, 43),    # In-vitro diagnostics -> Life Sciences Tools
    (2836, 2836, 41),    # Biological products -> Biotechnology
    (2840, 2843, 36),    # Soap & detergents -> Household Products
    (2844, 2844, 37),    # Cosmetics -> Personal Care Products
    (2900, 2999, 2),     # Petroleum refining
    # --- Rubber, plastics, minerals, metals ---
    (3000, 3099, 3),     # Rubber & plastics -> Chemicals
    (3011, 3011, 22),    # Tires -> Automobile Components
    (3200, 3299, 4),     # Stone, clay, glass -> Construction Materials
    (3300, 3399, 6),     # Primary metals -> Metals & Mining
    # --- Machinery & equipment ---
    (3400, 3499, 13),    # Fabricated metal -> Machinery
    (3500, 3599, 13),    # Industrial machinery
    (3570, 3579, 53),    # Computers -> Technology Hardware, Storage & Peripherals
    (3600, 3699, 11),    # Electrical equipment
    (3630, 3639, 24),    # Household appliances -> Household Durables
    (3651, 3652, 24),    # Household audio/video
    (3660, 3669, 52),    # Communications equipment
    (3670, 3679, 54),    # Electronic components
    (3674, 3674, 55),    # Semiconductors
    # --- Transport equipment ---
    (3700, 3716, 23),    # Motor vehicles -> Automobiles
    (3714, 3714, 22),    # Motor vehicle parts -> Automobile Components
    (3720, 3729, 8),     # Aircraft -> Aerospace & Defense
    (3730, 3739, 8),     # Ship & boat building
    (3740, 3749, 13),    # Railroad equipment -> Machinery
    (3751, 3751, 23),    # Motorcycles & bicycles -> Automobiles
    (3760, 3769, 8),     # Guided missiles
    (3790, 3799, 25),    # Recreational vehicles -> Leisure Products
    # --- Instruments & medical devices ---
    (3800, 3829, 54),    # Instruments -> Electronic Equipment & Instruments
    (3821, 3827, 43),    # Lab apparatus -> Life Sciences Tools
    (3840, 3851, 38),    # Medical instruments -> Health Care Equipment
    (3860, 3899, 25),    # Photographic, watches -> Leisure Products
    (3900, 3999, 25),    # Misc manufacturing -> Leisure Products
    # --- Transportation ---
    (4000, 4013, 20),    # Railroads -> Ground Transportation
    (4100, 4173, 20),    # Local transit
    (4200, 4299, 20),    # Trucking
    (4400, 4499, 19),    # Water transport -> Marine Transportation
    (4500, 4599, 18),    # Air transport -> Passenger Airlines
    (4513, 4513, 17),    # Air courier -> Air Freight & Logistics
    (4600, 4699, 2),     # Pipelines -> Oil, Gas & Consumable Fuels
    (4700, 4799, 17),    # Transportation services -> Air Freight & Logistics
    (4780, 4789, 21),    # Transportation infrastructure
    # --- Telecom & media ---
    (4800, 4899, 56),    # Telephone -> Diversified Telecommunication Services
    (4812, 4812, 57),    # Radiotelephone -> Wireless Telecommunication Services
    (4820, 4841, 58),    # Broadcasting & cable -> Media
    # --- Utilities ---
    (4900, 4999, 63),    # Utilities -> Multi-Utilities
    (4911, 4911, 61),    # Electric services -> Electric Utilities
    (4920, 4925, 62),    # Gas -> Gas Utilities
    (4940, 4949, 64),    # Water -> Water Utilities
    (4950, 4959, 15),    # Sanitary services -> Commercial Services & Supplies
    (4991, 4991, 65),    # Cogeneration -> Independent Power & Renewables
    # --- Wholesale ---
    (5000, 5099, 14),    # Wholesale durable -> Trading Companies & Distributors
    (5100, 5199, 32),    # Wholesale nondurable -> Consumer Staples Distribution
    (5122, 5122, 39),    # Drugs wholesale -> Health Care Providers & Services
    (5160, 5169, 3),     # Chemicals wholesale
    # --- Retail ---
    (5200, 5271, 31),    # Building materials -> Specialty Retail
    (5300, 5399, 30),    # General merchandise -> Broadline Retail
    (5400, 5499, 32),    # Food stores -> Consumer Staples Distribution & Retail
    (5500, 5599, 31),    # Auto dealers -> Specialty Retail
    (5600, 5799, 31),    # Apparel & furniture retail
    (5800, 5899, 27),    # Eating & drinking -> Hotels, Restaurants & Leisure
    (5900, 5912, 32),    # Drug stores
    (5940, 5999, 31),    # Misc retail -> Specialty Retail
    (5961, 5961, 30),    # Catalog & mail-order -> Broadline Retail
    # --- Financials ---
    (6000, 6099, 44),    # Banks
    (6100, 6159, 46),    # Credit institutions -> Consumer Finance
    (6160, 6199, 45),    # Finance services -> Financial Services
    (6200, 6299, 47),    # Brokers & exchanges -> Capital Markets
    (6300, 6411, 49),    # Insurance
    (6500, 6599, 74),    # Real estate -> Real Estate Management & Development
    (6726, 6726, 47),    # Investment offices -> Capital Markets
    (6770, 6770, 45),    # Blank checks / SPACs -> Financial Services
    (6794, 6794, 45),    # Patent owners & lessors -> Financial Services
    (6795, 6795, 6),     # Mineral royalty traders -> Metals & Mining
    (6798, 6798, 66),    # REITs -> Diversified REITs
    (6799, 6799, 47),    # Investors NEC -> Capital Markets
    # --- Services ---
    (7000, 7099, 27),    # Hotels -> Hotels, Restaurants & Leisure
    (7200, 7299, 28),    # Personal services -> Diversified Consumer Services
    (7310, 7319, 58),    # Advertising -> Media
    (7320, 7329, 16),    # Credit reporting -> Professional Services
    (7330, 7349, 15),    # Services to buildings -> Commercial Services & Supplies
    (7350, 7359, 14),    # Equipment rental & leasing -> Trading Companies & Distributors
    (7360, 7369, 16),    # Personnel supply -> Professional Services
    (7370, 7372, 51),    # Software
    (7373, 7379, 50),    # Computer services -> IT Services
    (7380, 7389, 16),    # Business services -> Professional Services
    (7500, 7549, 28),    # Auto repair -> Diversified Consumer Services
    (7600, 7699, 15),    # Misc repair
    (7800, 7841, 59),    # Motion pictures -> Entertainment
    (7900, 7999, 27),    # Amusement & recreation
    (8000, 8099, 39),    # Health services -> Health Care Providers & Services
    (8071, 8071, 43),    # Medical labs -> Life Sciences Tools
    (8200, 8399, 28),    # Education & social services
    (8700, 8713, 10),    # Engineering & architectural -> Construction & Engineering
    (8731, 8734, 43),    # Research & testing labs -> Life Sciences Tools
    (8741, 8749, 16),    # Management consulting -> Professional Services
    (8880, 8888, 45),    # Foreign conglomerates -> Financial Services
)

_BY_NUMBER: dict[int, IndustryBlueprint] = {b.number: b for b in BLUEPRINT}

# Legacy coarse sector -> GICS industry number. Used only when a company has no
# usable SIC code but does have the sector string that sic_map already derived.
# Deliberately omits ambiguous sectors ("Manufacturing", "Other", "Wholesale"):
# guessing an industry there would attach confidently-wrong KPIs, which is worse
# than falling back to the generic set.
_SECTOR_TO_GICS: dict[str, int] = {
    "Agriculture": 34,
    "Mining": 6,
    "Oil & Gas": 2,
    "Construction": 10,
    "Food & Beverage": 34,
    "Chemicals": 3,
    "Pharmaceuticals & Biotech": 42,
    "Computer Hardware": 53,
    "Electronics & Semiconductors": 54,
    "Semiconductors": 55,
    "Automotive": 23,
    "Transportation": 20,
    "Telecommunications": 56,
    "Utilities": 63,
    "Retail": 31,
    "Banking": 44,
    "Credit & Lending": 46,
    "Capital Markets": 47,
    "Insurance": 49,
    "Real Estate": 74,
    "REITs": 66,
    "Hospitality": 27,
    "Software & SaaS": 51,
    "IT Services": 50,
    "Media & Entertainment": 58,
    "Healthcare Services": 39,
}


def industry_for_sic(sic: str | None) -> IndustryBlueprint | None:
    """The GICS industry whose KPI set best fits this SIC code.

    Narrowest matching range wins, so a specific code (3674 semiconductors)
    overrides the broad group that contains it (3600-3699 electrical equipment).
    """
    if not sic:
        return None
    try:
        code = int(str(sic).strip())
    except (TypeError, ValueError):
        return None
    matches = [(hi - lo, number) for lo, hi, number in _SIC_TO_GICS if lo <= code <= hi]
    if not matches:
        return None
    return _BY_NUMBER.get(min(matches)[1])


def industry_for_sector(sector: str | None) -> IndustryBlueprint | None:
    """Fallback when SIC is missing or unmapped. Returns None for sectors too
    broad to pin to one industry — the caller should use generic KPIs there."""
    if not sector:
        return None
    number = _SECTOR_TO_GICS.get(sector)
    return _BY_NUMBER.get(number) if number else None


def industry_for_company(sic: str | None, sector: str | None) -> IndustryBlueprint | None:
    """Preferred resolution order: SIC (from the filing) then sector (derived)."""
    return industry_for_sic(sic) or industry_for_sector(sector)
