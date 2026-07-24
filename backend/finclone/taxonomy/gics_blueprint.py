"""GICS 74-Industry Master Blueprint (BOE Analytics, July 2026).

Encodes the firm's industry-model blueprint as structured data: every official
GICS industry with its anchor company, reusable template family, primary
valuation methods, and key operating KPIs — the drivers/metrics/multiples that
each industry's model is built around (M5 tasks 1-3).

Source of truth: BOE_GICS_74_Industry_Master_Blueprint.pdf. Taxonomy follows
MSCI GICS Methodology (April 2026): 11 sectors, 25 industry groups, 74
industries. The `template_family` is the reusable modeling engine (~15-20 of
them) assembled into industry-specific templates — this is the "standardized
modeling structure per GICS industry" the blueprint calls for.

Complexity is 1 (straightforward) to 5 (specialized). Phase is the proposed
build sequence (1 = highest-value anchors, 3 = niche/specialized).

NB: anchor companies are modeling anchors chosen for scale/disclosure/relevance,
not permanent market-cap leaders — revalidate before commercial use.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class IndustryBlueprint:
    number: int
    sector: str
    industry_group: str
    gics_industry: str
    anchor_company: str
    ticker: str
    template_family: str
    primary_valuation: tuple[str, ...]
    key_kpis: tuple[str, ...]
    complexity: int
    phase: int
    suggested_owner: str


def _v(s: str) -> tuple[str, ...]:
    return tuple(p.strip() for p in s.split(",") if p.strip())


def _k(s: str) -> tuple[str, ...]:
    return tuple(p.strip() for p in s.split(";") if p.strip())


# All 74 GICS industries. Ordered by the blueprint's row number.
BLUEPRINT: tuple[IndustryBlueprint, ...] = (
    # --- Energy (2) ---
    IndustryBlueprint(1, "Energy", "Energy", "Energy Equipment & Services", "SLB", "SLB", "Energy services", _v("EV/EBITDA, DCF"), _k("Rig activity; backlog; pricing; FCF"), 4, 2, "External specialist"),
    IndustryBlueprint(2, "Energy", "Energy", "Oil, Gas & Consumable Fuels", "Exxon Mobil", "XOM", "Integrated energy", _v("DCF, NAV, EV/EBITDA"), _k("Production; realized price; reserves; capex"), 5, 1, "BOE + energy specialist"),
    # --- Materials (5) ---
    IndustryBlueprint(3, "Materials", "Materials", "Chemicals", "Linde", "LIN", "Chemicals", _v("DCF, EV/EBITDA"), _k("Volume; price/mix; utilization; energy costs"), 3, 2, "BOE"),
    IndustryBlueprint(4, "Materials", "Materials", "Construction Materials", "CRH", "CRH", "Materials / building products", _v("DCF, EV/EBITDA"), _k("Volume; pricing; aggregates; backlog"), 3, 2, "BOE"),
    IndustryBlueprint(5, "Materials", "Materials", "Containers & Packaging", "Packaging Corp. of America", "PKG", "Packaging", _v("DCF, EV/EBITDA"), _k("Shipments; price/ton; utilization; fiber costs"), 3, 3, "Vendor"),
    IndustryBlueprint(6, "Materials", "Materials", "Metals & Mining", "Newmont", "NEM", "Mining", _v("NAV, DCF, EV/EBITDA"), _k("Production; grade; realized price; AISC; reserves"), 5, 2, "Mining specialist"),
    IndustryBlueprint(7, "Materials", "Materials", "Paper & Forest Products", "International Paper", "IP", "Paper & forest products", _v("DCF, EV/EBITDA"), _k("Tons; price/mix; pulp costs; utilization"), 3, 3, "Vendor"),
    # --- Industrials (14) ---
    IndustryBlueprint(8, "Industrials", "Capital Goods", "Aerospace & Defense", "RTX", "RTX", "Aerospace & defense", _v("DCF, EV/EBITDA"), _k("Backlog; bookings; deliveries; program margin"), 5, 1, "A&D specialist"),
    IndustryBlueprint(9, "Industrials", "Capital Goods", "Building Products", "Johnson Controls", "JCI", "Building products", _v("DCF, EV/EBITDA"), _k("Orders; backlog; price/cost; aftermarket"), 3, 2, "BOE"),
    IndustryBlueprint(10, "Industrials", "Capital Goods", "Construction & Engineering", "Quanta Services", "PWR", "Engineering & construction", _v("DCF, EV/EBITDA"), _k("Backlog; book-to-bill; project margin; cash conversion"), 4, 2, "Industrials specialist"),
    IndustryBlueprint(11, "Industrials", "Capital Goods", "Electrical Equipment", "Eaton", "ETN", "Electrical equipment", _v("DCF, EV/EBITDA"), _k("Orders; backlog; organic growth; segment margin"), 4, 1, "BOE"),
    IndustryBlueprint(12, "Industrials", "Capital Goods", "Industrial Conglomerates", "Honeywell", "HON", "Industrial conglomerate", _v("SOTP, DCF"), _k("Segment growth; margin; orders; portfolio mix"), 5, 2, "Senior analyst"),
    IndustryBlueprint(13, "Industrials", "Capital Goods", "Machinery", "Caterpillar", "CAT", "Machinery", _v("DCF, EV/EBITDA, P/E"), _k("Dealer inventory; volume; price; backlog"), 4, 1, "BOE"),
    IndustryBlueprint(14, "Industrials", "Capital Goods", "Trading Companies & Distributors", "W.W. Grainger", "GWW", "Distribution", _v("DCF, EV/EBITDA"), _k("Daily sales; price; volume; gross margin"), 3, 3, "Vendor"),
    IndustryBlueprint(15, "Industrials", "Commercial & Professional Services", "Commercial Services & Supplies", "Waste Management", "WM", "Business services", _v("DCF, EV/EBITDA"), _k("Yield; volume; route density; recycling prices"), 3, 2, "BOE"),
    IndustryBlueprint(16, "Industrials", "Commercial & Professional Services", "Professional Services", "Accenture", "ACN", "Professional services", _v("DCF, EV/EBITDA"), _k("Bookings; utilization; headcount; bill rates"), 3, 2, "BOE"),
    IndustryBlueprint(17, "Industrials", "Transportation", "Air Freight & Logistics", "UPS", "UPS", "Logistics", _v("DCF, EV/EBITDA"), _k("Package volume; yield; stops; labor cost"), 4, 2, "Transportation specialist"),
    IndustryBlueprint(18, "Industrials", "Transportation", "Passenger Airlines", "Delta Air Lines", "DAL", "Airlines", _v("EV/EBITDAR, DCF"), _k("ASM; RASM; CASM; load factor; fuel"), 5, 2, "Transportation specialist"),
    IndustryBlueprint(19, "Industrials", "Transportation", "Marine Transportation", "Matson", "MATX", "Marine transport", _v("DCF, EV/EBITDA"), _k("Container volume; freight rate; vessel utilization"), 4, 3, "External specialist"),
    IndustryBlueprint(20, "Industrials", "Transportation", "Ground Transportation", "Union Pacific", "UNP", "Rail / ground transport", _v("DCF, EV/EBITDA"), _k("Carloads; revenue/unit; OR; velocity"), 4, 2, "Transportation specialist"),
    IndustryBlueprint(21, "Industrials", "Transportation", "Transportation Infrastructure", "Ferrovial", "FER", "Infrastructure", _v("DCF, SOTP, EV/EBITDA"), _k("Traffic; toll yield; concession life; capex"), 5, 3, "Infrastructure specialist"),
    # --- Consumer Discretionary (10) ---
    IndustryBlueprint(22, "Consumer Discretionary", "Automobiles & Components", "Automobile Components", "Aptiv", "APTV", "Auto suppliers", _v("DCF, EV/EBITDA"), _k("Content/vehicle; production; backlog; margin"), 4, 2, "Auto specialist"),
    IndustryBlueprint(23, "Consumer Discretionary", "Automobiles & Components", "Automobiles", "Tesla", "TSLA", "Automotive", _v("DCF, EV/EBITDA, SOTP"), _k("Deliveries; ASP; auto margin; capacity"), 5, 1, "Auto specialist"),
    IndustryBlueprint(24, "Consumer Discretionary", "Consumer Durables & Apparel", "Household Durables", "D.R. Horton", "DHI", "Homebuilding / durables", _v("P/B, P/E, DCF"), _k("Orders; closings; ASP; gross margin; lots"), 4, 2, "Housing specialist"),
    IndustryBlueprint(25, "Consumer Discretionary", "Consumer Durables & Apparel", "Leisure Products", "Brunswick", "BC", "Leisure products", _v("DCF, EV/EBITDA"), _k("Units; dealer inventory; ASP; utilization"), 3, 3, "Vendor"),
    IndustryBlueprint(26, "Consumer Discretionary", "Consumer Durables & Apparel", "Textiles, Apparel & Luxury Goods", "Nike", "NKE", "Apparel & luxury", _v("DCF, EV/EBITDA"), _k("Units; ASP; DTC mix; inventory; gross margin"), 3, 2, "Consumer analyst"),
    IndustryBlueprint(27, "Consumer Discretionary", "Consumer Services", "Hotels, Restaurants & Leisure", "McDonald's", "MCD", "Restaurants / leisure", _v("DCF, EV/EBITDA"), _k("Same-store sales; units; franchise margin"), 4, 1, "Consumer analyst"),
    IndustryBlueprint(28, "Consumer Discretionary", "Consumer Services", "Diversified Consumer Services", "H&R Block", "HRB", "Consumer services", _v("DCF, P/E"), _k("Clients; revenue/client; retention; attach rate"), 3, 3, "Vendor"),
    IndustryBlueprint(29, "Consumer Discretionary", "Consumer Discretionary Distribution & Retail", "Distributors", "Pool Corp.", "POOL", "Distribution", _v("DCF, EV/EBITDA"), _k("Sales/day; volume; price; inventory turns"), 3, 3, "Vendor"),
    IndustryBlueprint(30, "Consumer Discretionary", "Consumer Discretionary Distribution & Retail", "Broadline Retail", "Amazon", "AMZN", "E-commerce + cloud", _v("SOTP, DCF, EV/EBITDA"), _k("GMV; AWS growth; fulfillment cost; ads"), 5, 1, "BOE"),
    IndustryBlueprint(31, "Consumer Discretionary", "Consumer Discretionary Distribution & Retail", "Specialty Retail", "Home Depot", "HD", "Retail", _v("DCF, EV/EBITDA, P/E"), _k("Comp sales; ticket; transactions; inventory turns"), 4, 1, "Consumer analyst"),
    # --- Consumer Staples (6) ---
    IndustryBlueprint(32, "Consumer Staples", "Consumer Staples Distribution & Retail", "Consumer Staples Distribution & Retail", "Walmart", "WMT", "Staples retail", _v("DCF, EV/EBITDA, P/E"), _k("Comp sales; traffic; ticket; e-commerce; margin"), 4, 1, "BOE"),
    IndustryBlueprint(33, "Consumer Staples", "Food, Beverage & Tobacco", "Beverages", "Coca-Cola", "KO", "Beverages", _v("DCF, EV/EBITDA"), _k("Unit case volume; price/mix; concentrate margin"), 3, 2, "Consumer analyst"),
    IndustryBlueprint(34, "Consumer Staples", "Food, Beverage & Tobacco", "Food Products", "Mondelez", "MDLZ", "Food products", _v("DCF, EV/EBITDA"), _k("Volume; pricing; commodities; gross margin"), 3, 2, "Consumer analyst"),
    IndustryBlueprint(35, "Consumer Staples", "Food, Beverage & Tobacco", "Tobacco", "Philip Morris", "PM", "Tobacco", _v("DCF, EV/EBITDA, dividend yield"), _k("Shipments; price/mix; smoke-free users; margin"), 4, 2, "Consumer analyst"),
    IndustryBlueprint(36, "Consumer Staples", "Household & Personal Products", "Household Products", "Procter & Gamble", "PG", "Household products", _v("DCF, EV/EBITDA"), _k("Organic sales; volume; price/mix; gross margin"), 3, 2, "BOE"),
    IndustryBlueprint(37, "Consumer Staples", "Household & Personal Products", "Personal Care Products", "Kenvue", "KVUE", "Personal care", _v("DCF, EV/EBITDA"), _k("Organic growth; price/mix; innovation; margin"), 3, 3, "Vendor"),
    # --- Health Care (6) ---
    IndustryBlueprint(38, "Health Care", "Health Care Equipment & Services", "Health Care Equipment & Supplies", "Intuitive Surgical", "ISRG", "Medtech", _v("DCF, EV/EBITDA"), _k("Procedures; installed base; system placements; utilization"), 4, 1, "Health care specialist"),
    IndustryBlueprint(39, "Health Care", "Health Care Equipment & Services", "Health Care Providers & Services", "UnitedHealth Group", "UNH", "Managed care / providers", _v("P/E, DCF"), _k("Members; premiums; MCR; Optum growth"), 5, 1, "Health care specialist"),
    IndustryBlueprint(40, "Health Care", "Health Care Equipment & Services", "Health Care Technology", "Veeva Systems", "VEEV", "Health care software", _v("DCF, EV/revenue, EV/FCF"), _k("Subscription growth; retention; backlog; margin"), 4, 2, "BOE"),
    IndustryBlueprint(41, "Health Care", "Pharmaceuticals, Biotechnology & Life Sciences", "Biotechnology", "AbbVie", "ABBV", "Biopharma", _v("Risk-adjusted DCF, P/E"), _k("Drug sales; patient share; pipeline; LOE"), 5, 1, "Biopharma specialist"),
    IndustryBlueprint(42, "Health Care", "Pharmaceuticals, Biotechnology & Life Sciences", "Pharmaceuticals", "Eli Lilly", "LLY", "Pharma", _v("Risk-adjusted DCF, P/E"), _k("Volume; price; indications; pipeline probability"), 5, 1, "Biopharma specialist"),
    IndustryBlueprint(43, "Health Care", "Pharmaceuticals, Biotechnology & Life Sciences", "Life Sciences Tools & Services", "Thermo Fisher Scientific", "TMO", "Life sciences tools", _v("DCF, EV/EBITDA"), _k("Organic growth; bioproduction demand; backlog; margin"), 4, 2, "Health care specialist"),
    # --- Financials (6) ---
    IndustryBlueprint(44, "Financials", "Banks", "Banks", "JPMorgan Chase", "JPM", "Bank", _v("P/TBV, P/E, ROTCE"), _k("NIM; loans; deposits; NCOs; CET1; ROTCE"), 5, 1, "Financials specialist"),
    IndustryBlueprint(45, "Financials", "Financial Services", "Financial Services", "Berkshire Hathaway", "BRK.B", "Diversified financials", _v("SOTP, P/B, look-through earnings"), _k("Insurance float; underwriting; investment income; BV"), 5, 1, "Senior analyst"),
    IndustryBlueprint(46, "Financials", "Financial Services", "Consumer Finance", "American Express", "AXP", "Consumer finance", _v("P/E, DCF"), _k("Billings; loans; NCOs; discount rate; rewards"), 5, 2, "Financials specialist"),
    IndustryBlueprint(47, "Financials", "Financial Services", "Capital Markets", "S&P Global", "SPGI", "Capital markets / data", _v("DCF, EV/EBITDA"), _k("Issuance; subscription growth; retention; margins"), 4, 1, "BOE"),
    IndustryBlueprint(48, "Financials", "Financial Services", "Mortgage Real Estate Investment Trusts (REITs)", "Annaly Capital Management", "NLY", "Mortgage REIT", _v("P/B, dividend yield, economic return"), _k("Book value; spread; leverage; CPR; hedge cost"), 5, 3, "Mortgage specialist"),
    IndustryBlueprint(49, "Financials", "Insurance", "Insurance", "Progressive", "PGR", "Insurance", _v("P/B, P/E, ROE"), _k("Premium growth; combined ratio; retention; reserves"), 5, 1, "Insurance specialist"),
    # --- Information Technology (6) ---
    IndustryBlueprint(50, "Information Technology", "Software & Services", "IT Services", "IBM", "IBM", "IT services", _v("DCF, EV/FCF"), _k("Bookings; backlog; recurring mix; FCF conversion"), 4, 2, "BOE"),
    IndustryBlueprint(51, "Information Technology", "Software & Services", "Software", "Microsoft", "MSFT", "Software / SaaS", _v("DCF, EV/FCF, SOTP"), _k("ARR; Azure growth; RPO; seats; margin; SBC"), 5, 1, "BOE"),
    IndustryBlueprint(52, "Information Technology", "Technology Hardware & Equipment", "Communications Equipment", "Cisco Systems", "CSCO", "Communications equipment", _v("DCF, EV/FCF"), _k("Product orders; backlog; ARR; gross margin"), 4, 2, "Technology specialist"),
    IndustryBlueprint(53, "Information Technology", "Technology Hardware & Equipment", "Technology Hardware, Storage & Peripherals", "Apple", "AAPL", "Hardware ecosystem", _v("DCF, P/E"), _k("Units; ASP; installed base; services mix; margin"), 5, 1, "BOE"),
    IndustryBlueprint(54, "Information Technology", "Technology Hardware & Equipment", "Electronic Equipment, Instruments & Components", "Amphenol", "APH", "Electronic components", _v("DCF, EV/EBITDA"), _k("Organic growth; content; end-market mix; margin"), 4, 2, "Technology specialist"),
    IndustryBlueprint(55, "Information Technology", "Semiconductors & Semiconductor Equipment", "Semiconductors & Semiconductor Equipment", "NVIDIA", "NVDA", "Semiconductors", _v("DCF, P/E, EV/EBITDA"), _k("Units; ASP; data-center demand; gross margin; capex"), 5, 1, "Semiconductor specialist"),
    # --- Communication Services (5) ---
    IndustryBlueprint(56, "Communication Services", "Telecommunication Services", "Diversified Telecommunication Services", "AT&T", "T", "Telecom", _v("DCF, EV/EBITDA, dividend yield"), _k("Subscribers; ARPU; churn; fiber adds; capex"), 4, 2, "Telecom specialist"),
    IndustryBlueprint(57, "Communication Services", "Telecommunication Services", "Wireless Telecommunication Services", "T-Mobile US", "TMUS", "Wireless telecom", _v("DCF, EV/EBITDA"), _k("Net adds; ARPU; churn; spectrum; FCF"), 4, 1, "Telecom specialist"),
    IndustryBlueprint(58, "Communication Services", "Media & Entertainment", "Media", "Comcast", "CMCSA", "Media / cable", _v("SOTP, DCF, EV/EBITDA"), _k("Broadband adds; ARPU; ad revenue; theme parks"), 5, 2, "Media specialist"),
    IndustryBlueprint(59, "Communication Services", "Media & Entertainment", "Entertainment", "Netflix", "NFLX", "Streaming / entertainment", _v("DCF, EV/EBITDA"), _k("Members; ARPU; engagement; content spend; margin"), 5, 1, "Media specialist"),
    IndustryBlueprint(60, "Communication Services", "Media & Entertainment", "Interactive Media & Services", "Alphabet", "GOOGL", "Internet platform", _v("SOTP, DCF, EV/EBITDA"), _k("Search revenue; CPC; cloud growth; TAC; capex"), 5, 1, "BOE"),
    # --- Utilities (5) ---
    IndustryBlueprint(61, "Utilities", "Utilities", "Electric Utilities", "NextEra Energy", "NEE", "Regulated utility + renewables", _v("DCF, P/E, dividend yield"), _k("Rate base; allowed ROE; load; generation; capex"), 5, 1, "Utilities specialist"),
    IndustryBlueprint(62, "Utilities", "Utilities", "Gas Utilities", "Atmos Energy", "ATO", "Gas utility", _v("DCF, P/E, dividend yield"), _k("Rate base; customers; allowed ROE; capex"), 4, 2, "Utilities specialist"),
    IndustryBlueprint(63, "Utilities", "Utilities", "Multi-Utilities", "Sempra", "SRE", "Multi-utility", _v("SOTP, DCF, P/E"), _k("Rate base; allowed ROE; utility mix; capex"), 5, 2, "Utilities specialist"),
    IndustryBlueprint(64, "Utilities", "Utilities", "Water Utilities", "American Water Works", "AWK", "Water utility", _v("DCF, P/E, dividend yield"), _k("Rate base; connections; allowed ROE; capex"), 4, 3, "Utilities specialist"),
    IndustryBlueprint(65, "Utilities", "Utilities", "Independent Power and Renewable Electricity Producers", "Constellation Energy", "CEG", "Power producer", _v("DCF, EV/EBITDA"), _k("Generation; realized power price; capacity factor; hedges"), 5, 1, "Power specialist"),
    # --- Real Estate (9) ---
    IndustryBlueprint(66, "Real Estate", "Equity Real Estate Investment Trusts (REITs)", "Diversified REITs", "W.P. Carey", "WPC", "Diversified REIT", _v("NAV, AFFO, dividend yield"), _k("Occupancy; rent growth; cap rate; AFFO/share"), 4, 3, "REIT specialist"),
    IndustryBlueprint(67, "Real Estate", "Equity Real Estate Investment Trusts (REITs)", "Industrial REITs", "Prologis", "PLD", "Industrial REIT", _v("NAV, AFFO, implied cap rate"), _k("Occupancy; rent growth; development starts; AFFO"), 4, 1, "REIT specialist"),
    IndustryBlueprint(68, "Real Estate", "Equity Real Estate Investment Trusts (REITs)", "Hotel & Resort REITs", "Host Hotels & Resorts", "HST", "Hotel REIT", _v("NAV, AFFO, EV/EBITDA"), _k("RevPAR; occupancy; ADR; hotel EBITDA margin"), 4, 3, "REIT specialist"),
    IndustryBlueprint(69, "Real Estate", "Equity Real Estate Investment Trusts (REITs)", "Office REITs", "BXP", "BXP", "Office REIT", _v("NAV, AFFO, implied cap rate"), _k("Occupancy; leasing spreads; expirations; NOI"), 5, 3, "REIT specialist"),
    IndustryBlueprint(70, "Real Estate", "Equity Real Estate Investment Trusts (REITs)", "Health Care REITs", "Welltower", "WELL", "Health care REIT", _v("NAV, AFFO, implied cap rate"), _k("Occupancy; same-store NOI; rent coverage; capex"), 4, 2, "REIT specialist"),
    IndustryBlueprint(71, "Real Estate", "Equity Real Estate Investment Trusts (REITs)", "Residential REITs", "AvalonBay Communities", "AVB", "Residential REIT", _v("NAV, AFFO, implied cap rate"), _k("Occupancy; rent growth; turnover; same-store NOI"), 4, 2, "REIT specialist"),
    IndustryBlueprint(72, "Real Estate", "Equity Real Estate Investment Trusts (REITs)", "Retail REITs", "Simon Property Group", "SPG", "Retail REIT", _v("NAV, AFFO, dividend yield"), _k("Occupancy; leasing spreads; sales/sq ft; NOI"), 4, 2, "REIT specialist"),
    IndustryBlueprint(73, "Real Estate", "Equity Real Estate Investment Trusts (REITs)", "Specialized REITs", "Equinix", "EQIX", "Specialized REIT", _v("NAV, AFFO, EV/EBITDA"), _k("Cabinets; MRR; churn; utilization; development"), 5, 1, "REIT specialist"),
    IndustryBlueprint(74, "Real Estate", "Real Estate Management & Development", "Real Estate Management & Development", "CoStar Group", "CSGP", "Real estate services / data", _v("DCF, EV/revenue, EV/EBITDA"), _k("Subscribers; ARPU; traffic; bookings; margin"), 4, 2, "BOE"),
)


# --- Lookups -----------------------------------------------------------------

BY_TICKER: dict[str, IndustryBlueprint] = {b.ticker: b for b in BLUEPRINT}
BY_INDUSTRY: dict[str, IndustryBlueprint] = {b.gics_industry: b for b in BLUEPRINT}


def for_ticker(ticker: str) -> IndustryBlueprint | None:
    """The blueprint whose anchor company matches this ticker (exact anchors
    only — most tickers won't be anchors; use for_industry for coverage)."""
    return BY_TICKER.get(ticker.upper())


def for_industry(gics_industry: str) -> IndustryBlueprint | None:
    return BY_INDUSTRY.get(gics_industry)


def by_phase(phase: int) -> list[IndustryBlueprint]:
    """Industries in a given build phase (1 = highest-value anchors)."""
    return [b for b in BLUEPRINT if b.phase == phase]


def by_sector(sector: str) -> list[IndustryBlueprint]:
    return [b for b in BLUEPRINT if b.sector == sector]


def template_families() -> dict[str, list[IndustryBlueprint]]:
    """The reusable modeling engines grouped to the industries that share them —
    the ~15-20 core families the blueprint standardizes models around."""
    families: dict[str, list[IndustryBlueprint]] = {}
    for b in BLUEPRINT:
        families.setdefault(b.template_family, []).append(b)
    return families


# Sanity: the official GICS structure has exactly 74 industries.
assert len(BLUEPRINT) == 74, f"expected 74 GICS industries, got {len(BLUEPRINT)}"
assert len(BY_TICKER) == 74, "duplicate anchor ticker in blueprint"
