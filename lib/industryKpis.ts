/**
 * Industry-specific KPI tab configuration for Excel generation.
 * Matched against a company's sector/industry strings (case-insensitive).
 */

export interface IndustryKpi {
  name: string;
  /** Short explanation written next to the KPI row in the tab. */
  note: string;
  /** SimFin line items that relate to this KPI — pulled into the tab when present. */
  relatedLineItems?: string[];
}

export interface IndustryTabConfig {
  tabName: string;
  kpis: IndustryKpi[];
}

const INDUSTRY_TAB_RULES: { match: RegExp; config: IndustryTabConfig }[] = [
  {
    match: /software|saas|internet|technology services/i,
    config: {
      tabName: "SaaS KPIs",
      kpis: [
        { name: "ARR (Annual Recurring Revenue)", note: "Recurring revenue run-rate; approximate from subscription revenue.", relatedLineItems: ["Revenue"] },
        { name: "Revenue Growth %", note: "YoY growth of total revenue.", relatedLineItems: ["Revenue"] },
        { name: "Gross Margin %", note: "Gross Profit / Revenue.", relatedLineItems: ["Gross Profit", "Revenue"] },
        { name: "Rule of 40", note: "Revenue growth % + FCF margin %." },
        { name: "Net Revenue Retention", note: "Not disclosed in statements; source from filings/IR." },
      ],
    },
  },
  {
    match: /hotel|hospitality|resort|casino|lodging|restaurant/i,
    config: {
      tabName: "Hospitality KPIs",
      kpis: [
        { name: "RevPAR", note: "Revenue per available room = ADR × Occupancy.", relatedLineItems: ["Revenue"] },
        { name: "ADR (Average Daily Rate)", note: "Room revenue / rooms sold; source from filings." },
        { name: "Occupancy %", note: "Rooms sold / rooms available; source from filings." },
        { name: "EBITDA Margin %", note: "EBITDA / Revenue.", relatedLineItems: ["EBITDA", "Revenue"] },
      ],
    },
  },
  {
    match: /retail|consumer cyclical|apparel|grocery|department store/i,
    config: {
      tabName: "Retail KPIs",
      kpis: [
        { name: "Same-Store Sales Growth %", note: "Comparable store sales; source from filings." },
        { name: "Inventory Turnover", note: "COGS / average inventory.", relatedLineItems: ["Cost of Revenue", "Inventories"] },
        { name: "Gross Margin %", note: "Gross Profit / Revenue.", relatedLineItems: ["Gross Profit", "Revenue"] },
      ],
    },
  },
  {
    match: /bank|financial services|insurance|capital markets/i,
    config: {
      tabName: "Financials KPIs",
      kpis: [
        { name: "Net Interest Margin %", note: "Net interest income / earning assets.", relatedLineItems: ["Net Interest Income"] },
        { name: "Efficiency Ratio %", note: "Non-interest expense / revenue." },
        { name: "Return on Equity %", note: "Net Income / Total Equity.", relatedLineItems: ["Net Income", "Total Equity"] },
      ],
    },
  },
  {
    match: /airline|aviation|air freight/i,
    config: {
      tabName: "Airline KPIs",
      kpis: [
        { name: "RASM", note: "Revenue per available seat mile; source from filings.", relatedLineItems: ["Revenue"] },
        { name: "CASM", note: "Cost per available seat mile; source from filings." },
        { name: "Load Factor %", note: "RPMs / ASMs; source from filings." },
      ],
    },
  },
  {
    match: /oil|gas|energy|petroleum|mining/i,
    config: {
      tabName: "Energy KPIs",
      kpis: [
        { name: "Production Volume", note: "BOE/day; source from filings." },
        { name: "Realized Price", note: "Average realized price per BOE; source from filings." },
        { name: "FCF", note: "Operating cash flow − capex.", relatedLineItems: ["Net Cash from Operating Activities", "Change in Fixed Assets & Intangibles"] },
      ],
    },
  },
];

export function getIndustryTabs(
  sector: string | null,
  industry: string | null
): IndustryTabConfig[] {
  const haystack = `${sector ?? ""} ${industry ?? ""}`.trim();
  if (!haystack) return [];
  return INDUSTRY_TAB_RULES.filter((rule) => rule.match.test(haystack)).map(
    (rule) => rule.config
  );
}
