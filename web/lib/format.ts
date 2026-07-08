// Financial number formatting: millions with parenthesized negatives.
export function fmtMoney(value: number): string {
  const millions = value / 1_000_000;
  const abs = Math.abs(millions);
  const text =
    abs >= 1000
      ? (abs / 1000).toLocaleString("en-US", { maximumFractionDigits: 1 }) + "B"
      : abs.toLocaleString("en-US", { maximumFractionDigits: 0 }) + "M";
  return millions < 0 ? `(${text})` : text;
}

export function fmtPlain(value: number): string {
  const abs = Math.abs(value).toLocaleString("en-US", { maximumFractionDigits: 2 });
  return value < 0 ? `(${abs})` : abs;
}

// Display order + labels for the statement table
export const CONCEPT_LABELS: [string, string][] = [
  ["revenue", "Revenue"],
  ["cost_of_revenue", "Cost of Revenue"],
  ["gross_profit", "Gross Profit"],
  ["research_development", "R&D"],
  ["sga_expense", "SG&A"],
  ["operating_income", "Operating Income"],
  ["net_income", "Net Income"],
  ["eps_diluted", "Diluted EPS"],
  ["operating_cash_flow", "Operating Cash Flow"],
  ["capex", "CapEx"],
  ["stock_based_compensation", "Stock-Based Comp"],
  ["cash_and_equivalents", "Cash & Equivalents"],
  ["total_assets", "Total Assets"],
  ["total_liabilities", "Total Liabilities"],
  ["stockholders_equity", "Stockholders' Equity"],
  ["long_term_debt", "Long-Term Debt"],
];

// Concepts formatted per-share / per-unit rather than in millions
export const PLAIN_CONCEPTS = new Set(["eps_diluted"]);

// XBRL EPS is as-reported: after a stock split, companies restate only the two
// comparative years in the next 10-K, so older fiscal years keep pre-split EPS
// forever (e.g. GOOGL pre-2020 vs post-2022 after the 20:1 split). To display
// one consistent (current) basis, infer each year's cumulative split factor
// from implied diluted shares (net income ÷ EPS) relative to the most recent
// year, snapped to plausible split ratios to absorb buyback/issuance drift.
const SPLIT_FACTORS = [2, 3, 4, 5, 6, 7, 8, 10, 12, 14, 15, 20, 21, 25, 28, 30, 40, 50];

export function epsSplitFactor(
  epsYear: number, niYear: number,
  epsRef: number, niRef: number,
): number {
  if (!epsYear || !niYear || !epsRef || !niRef) return 1;
  const sharesYear = Math.abs(niYear / epsYear);
  const sharesRef = Math.abs(niRef / epsRef);
  if (sharesYear <= 0 || sharesRef <= 0) return 1;
  const ratio = sharesRef / sharesYear;
  if (ratio < 1.5) return 1; // buyback/issuance noise, not a split
  let best = 1;
  let bestDist = Infinity;
  for (const f of SPLIT_FACTORS) {
    const d = Math.abs(Math.log(ratio / f));
    if (d < bestDist) { bestDist = d; best = f; }
  }
  return best;
}
