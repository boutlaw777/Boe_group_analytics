"""Map raw US-GAAP XBRL tags onto FinClone's canonical concept set.

Companies tag the same economic concept with different US-GAAP elements
(e.g. Revenues vs RevenueFromContractWithCustomerExcludingAssessedTax), and
switch tags across years. Each canonical concept lists acceptable tags in
priority order; when a period has values under several tags, the
highest-priority tag wins.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class CanonicalConcept:
    name: str
    tags: tuple[str, ...]  # priority order, highest first
    is_flow: bool  # flows (revenue) can derive Q4 = FY - Q1 - Q2 - Q3; stocks (cash) cannot


CANONICAL_CONCEPTS: tuple[CanonicalConcept, ...] = (
    CanonicalConcept("revenue", (
        "RevenueFromContractWithCustomerExcludingAssessedTax",
        "RevenueFromContractWithCustomerIncludingAssessedTax",
        "Revenues",
        "SalesRevenueNet",
    ), is_flow=True),
    CanonicalConcept("cost_of_revenue", (
        "CostOfRevenue",
        "CostOfGoodsAndServicesSold",
        "CostOfGoodsSold",
    ), is_flow=True),
    CanonicalConcept("gross_profit", ("GrossProfit",), is_flow=True),
    CanonicalConcept("research_development", (
        "ResearchAndDevelopmentExpense",
    ), is_flow=True),
    CanonicalConcept("sga_expense", (
        "SellingGeneralAndAdministrativeExpense",
        "GeneralAndAdministrativeExpense",
    ), is_flow=True),
    CanonicalConcept("operating_income", ("OperatingIncomeLoss",), is_flow=True),
    CanonicalConcept("net_income", (
        "NetIncomeLoss",
        "ProfitLoss",
    ), is_flow=True),
    CanonicalConcept("eps_diluted", ("EarningsPerShareDiluted",), is_flow=True),
    CanonicalConcept("shares_diluted", (
        "WeightedAverageNumberOfDilutedSharesOutstanding",
    ), is_flow=True),
    CanonicalConcept("operating_cash_flow", (
        "NetCashProvidedByUsedInOperatingActivities",
        "NetCashProvidedByUsedInOperatingActivitiesContinuingOperations",
    ), is_flow=True),
    CanonicalConcept("capex", (
        "PaymentsToAcquirePropertyPlantAndEquipment",
    ), is_flow=True),
    CanonicalConcept("stock_based_compensation", (
        "ShareBasedCompensation",
    ), is_flow=True),
    CanonicalConcept("cash_and_equivalents", (
        "CashAndCashEquivalentsAtCarryingValue",
    ), is_flow=False),
    CanonicalConcept("total_assets", ("Assets",), is_flow=False),
    CanonicalConcept("total_liabilities", ("Liabilities",), is_flow=False),
    CanonicalConcept("stockholders_equity", (
        "StockholdersEquity",
        "StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest",
    ), is_flow=False),
    CanonicalConcept("long_term_debt", (
        "LongTermDebtNoncurrent",
        "LongTermDebt",
    ), is_flow=False),
)

# raw tag -> (canonical name, priority index, is_flow)
TAG_INDEX: dict[str, tuple[str, int, bool]] = {
    tag: (concept.name, priority, concept.is_flow)
    for concept in CANONICAL_CONCEPTS
    for priority, tag in enumerate(concept.tags)
}


def classify_tag(tag: str) -> tuple[str, int, bool] | None:
    """Return (canonical_name, priority, is_flow) for a raw tag, or None if unmapped."""
    return TAG_INDEX.get(tag)


def is_quarterly_duration(start_date: str | None, end_date: str) -> bool:
    """True when a duration fact spans roughly one quarter (~13 weeks).

    companyfacts durations also include YTD spans (6mo, 9mo) under Q2/Q3 fiscal
    periods; those must be excluded or they'd overwrite the discrete quarter.
    """
    if not start_date:
        return False
    from datetime import date

    start = date.fromisoformat(start_date)
    end = date.fromisoformat(end_date)
    return 75 <= (end - start).days <= 105


def is_annual_duration(start_date: str | None, end_date: str) -> bool:
    if not start_date:
        return False
    from datetime import date

    start = date.fromisoformat(start_date)
    end = date.fromisoformat(end_date)
    return 340 <= (end - start).days <= 390
