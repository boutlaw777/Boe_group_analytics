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
    CanonicalConcept("interest_expense", (
        # Filers split this three ways. Order matters: the gross expense lines
        # come first because InterestIncomeExpenseNet is a *net* figure with the
        # opposite sign convention, and would silently flip cost of debt.
        "InterestExpense",
        "InterestExpenseNonoperating",
        "InterestExpenseDebt",
    ), is_flow=True),
    CanonicalConcept("income_tax_expense", ("IncomeTaxExpenseBenefit",), is_flow=True),
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
    CanonicalConcept("depreciation_amortization", (
        "DepreciationDepletionAndAmortization",
        "DepreciationAmortizationAndAccretionNet",
        "DepreciationAndAmortization",
    ), is_flow=True),
    CanonicalConcept("cash_and_equivalents", (
        "CashAndCashEquivalentsAtCarryingValue",
    ), is_flow=False),
    CanonicalConcept("accounts_receivable", (
        "AccountsReceivableNetCurrent",
        "ReceivablesNetCurrent",
    ), is_flow=False),
    CanonicalConcept("inventory", ("InventoryNet",), is_flow=False),
    CanonicalConcept("total_current_assets", ("AssetsCurrent",), is_flow=False),
    CanonicalConcept("ppe_net", ("PropertyPlantAndEquipmentNet",), is_flow=False),
    CanonicalConcept("total_assets", ("Assets",), is_flow=False),
    CanonicalConcept("accounts_payable", (
        "AccountsPayableCurrent",
        "AccountsPayableAndAccruedLiabilitiesCurrent",
    ), is_flow=False),
    CanonicalConcept("total_current_liabilities", ("LiabilitiesCurrent",), is_flow=False),
    CanonicalConcept("total_liabilities", ("Liabilities",), is_flow=False),
    CanonicalConcept("stockholders_equity", (
        "StockholdersEquity",
        "StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest",
    ), is_flow=False),
    # --- debt, split by maturity -------------------------------------------
    # long_term_debt is deliberately NON-CURRENT only. The FY2023-FY2025 AAPL
    # validation flags come from comparing it against a reference source that
    # reports *total* term debt: 78.3 + 12.4 = 90.7 (FY2025), 85.8 + 10.9 = 96.7
    # (FY2024), 95.3 + 9.8 = 105.1 (FY2023). Both figures are correct; they
    # answer different questions. Keep the maturity split explicit so a
    # consumer can add the pieces rather than guess what a total contains.
    CanonicalConcept("long_term_debt", (
        "LongTermDebtNoncurrent",
        "LongTermDebt",
    ), is_flow=False),
    # Current debt: some filers report a single total (DebtCurrent), others only
    # the components. Captured separately because priority-order picking returns
    # ONE tag per concept — for a filer reporting commercial paper and current
    # term debt as separate lines, picking either alone understates current debt.
    CanonicalConcept("debt_current", ("DebtCurrent",), is_flow=False),
    CanonicalConcept("long_term_debt_current", ("LongTermDebtCurrent",), is_flow=False),
    CanonicalConcept("commercial_paper", ("CommercialPaper",), is_flow=False),
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
