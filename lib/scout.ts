/**
 * Scout — AI search & screener. SERVER-SIDE ONLY (uses ANTHROPIC_API_KEY).
 *
 * Flow: natural-language query → Claude parses it into a structured filter
 * (via structured outputs, schema-validated) → filter runs against the
 * Supabase `financials`/`companies` cache.
 */
import Anthropic from "@anthropic-ai/sdk";
import { z } from "zod";
import { zodOutputFormat } from "@anthropic-ai/sdk/helpers/zod";
import { getSupabase } from "./supabase";

export const ScoutIntentSchema = z.object({
  queryType: z
    .enum(["screen", "lookup"])
    .describe(
      "'screen' when the query filters a universe of companies by criteria. 'lookup' when it asks about ONE specific company (a ticker or company name is mentioned as the subject, e.g. 'Total Debt of GOOG', 'Apple's revenue') — lookups are not screens."
    ),
  ticker: z
    .string()
    .nullable()
    .describe(
      "For lookup queries: the ticker of the company being asked about (resolve names, e.g. 'Google' -> 'GOOG', 'the GOOG' -> 'GOOG'). Null for screen queries."
    ),
  sector: z
    .string()
    .nullable()
    .describe(
      "Sector or industry keyword to match, e.g. 'Software', 'Retail'. Null if the query doesn't restrict sector."
    ),
  metric: z
    .string()
    .describe(
      "The financial line item asked about, using SimFin naming: 'Revenue', 'Net Income', 'Gross Profit', 'Operating Income (Loss)', 'Total Assets', 'Total Equity', etc."
    ),
  isGrowth: z
    .boolean()
    .describe(
      "True when the query asks about growth/change of the metric (e.g. 'revenue growth over 20%') rather than its absolute value."
    ),
  operator: z
    .enum([">", "<", ">=", "<=", "="])
    .nullable()
    .describe(
      "Comparison operator stated or clearly implied by the query. Null when the query gives no comparison — NEVER invent one."
    ),
  value: z
    .number()
    .nullable()
    .describe(
      "Threshold to compare against. For growth metrics this is a percentage (20 means 20%). For absolute metrics it is in raw currency units (one billion dollars = 1000000000). Null when the query names a metric but NO numeric threshold — never invent a default like 0."
    ),
  fiscalYear: z
    .number()
    .nullable()
    .describe("Specific fiscal year mentioned in the query, else null."),
});

export type ScoutIntent = z.infer<typeof ScoutIntentSchema>;

/** A fully-specified screen: what screenCompanies() actually needs to run. */
export interface ScreenFilter {
  sector: string | null;
  metric: string;
  isGrowth: boolean;
  operator: ">" | "<" | ">=" | "<=" | "=";
  value: number;
  fiscalYear: number | null;
}

export interface ScreenResult {
  companyId: string;
  ticker: string;
  name: string;
  sector: string | null;
  industry: string | null;
  metricValue: number;
  fiscalYear: number;
}

const SYSTEM_PROMPT = `You convert natural-language stock screener queries into a structured filter.
The screener runs over cached fundamental data with SimFin line-item names.
Interpret money amounts fully (e.g. "over $1B revenue" -> metric "Revenue", operator ">", value 1000000000).
Growth queries (e.g. "growing revenue 20%+") set isGrowth true with value as the percentage number.
If the query names a sector loosely ("tech companies"), map it to a sector keyword ("Technology").
Single-company questions ("Total Debt of GOOG", "Apple's revenue in 2023") are queryType "lookup" with the ticker set — they are data lookups, not screens.
If a screen query states NO numeric threshold ("companies with Sales Per Share"), set operator and value to null. NEVER fabricate a threshold such as "> 0".`;

let anthropic: Anthropic | null = null;

function getAnthropic(): Anthropic {
  if (anthropic) return anthropic;
  if (!process.env.ANTHROPIC_API_KEY) {
    throw new Error(
      "ANTHROPIC_API_KEY is not set. Add it to .env.local to use Scout."
    );
  }
  anthropic = new Anthropic();
  return anthropic;
}

/** Parse a natural-language screener query into a structured intent. */
export async function parseScreenQuery(query: string): Promise<ScoutIntent> {
  const client = getAnthropic();

  const response = await client.messages.parse({
    model: "claude-opus-4-8",
    max_tokens: 2048,
    system: SYSTEM_PROMPT,
    messages: [{ role: "user", content: query }],
    output_config: {
      format: zodOutputFormat(ScoutIntentSchema),
    },
  });

  if (!response.parsed_output) {
    throw new Error("Could not interpret the search query — try rephrasing it.");
  }
  return response.parsed_output;
}

function compare(a: number, op: ScreenFilter["operator"], b: number): boolean {
  switch (op) {
    case ">":
      return a > b;
    case "<":
      return a < b;
    case ">=":
      return a >= b;
    case "<=":
      return a <= b;
    case "=":
      return a === b;
  }
}

/**
 * Run a structured filter against the Supabase cache.
 * NOTE: this screens across companies whose financials have been loaded into
 * the cache (SimFin free tier can't bulk-fetch the whole universe).
 */
export async function screenCompanies(
  filter: ScreenFilter
): Promise<ScreenResult[]> {
  const supabase = getSupabase();

  let query = supabase
    .from("financials")
    .select(
      "value, fiscal_year, companies!inner(id, ticker, name, sector, industry)"
    )
    .eq("line_item", filter.metric)
    .eq("period", "FY")
    .not("value", "is", null);

  if (filter.sector) {
    query = query.or(
      `sector.ilike.%${filter.sector}%,industry.ilike.%${filter.sector}%`,
      { referencedTable: "companies" }
    );
  }
  if (filter.fiscalYear && !filter.isGrowth) {
    query = query.eq("fiscal_year", filter.fiscalYear);
  }

  const { data, error } = await query;
  if (error) throw new Error(`Supabase screen query failed: ${error.message}`);

  interface Row {
    value: number;
    fiscal_year: number;
    companies: {
      id: string;
      ticker: string;
      name: string;
      sector: string | null;
      industry: string | null;
    };
  }
  const rows = (data ?? []) as unknown as Row[];

  // Group rows by company, newest year first.
  const byCompany = new Map<string, Row[]>();
  for (const row of rows) {
    const list = byCompany.get(row.companies.id) ?? [];
    list.push(row);
    byCompany.set(row.companies.id, list);
  }

  const results: ScreenResult[] = [];
  for (const list of byCompany.values()) {
    list.sort((a, b) => b.fiscal_year - a.fiscal_year);
    const company = list[0].companies;

    let metricValue: number;
    let fiscalYear: number;

    if (filter.isGrowth) {
      // Growth needs two consecutive fiscal years.
      const target = filter.fiscalYear
        ? list.find((r) => r.fiscal_year === filter.fiscalYear)
        : list[0];
      if (!target) continue;
      const prior = list.find((r) => r.fiscal_year === target.fiscal_year - 1);
      if (!prior || prior.value === 0) continue;
      metricValue =
        ((target.value - prior.value) / Math.abs(prior.value)) * 100;
      fiscalYear = target.fiscal_year;
    } else {
      metricValue = list[0].value;
      fiscalYear = list[0].fiscal_year;
    }

    if (compare(metricValue, filter.operator, filter.value)) {
      results.push({
        companyId: company.id,
        ticker: company.ticker,
        name: company.name,
        sector: company.sector,
        industry: company.industry,
        metricValue,
        fiscalYear,
      });
    }
  }

  results.sort((a, b) => b.metricValue - a.metricValue);
  return results;
}
