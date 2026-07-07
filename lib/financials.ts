/**
 * Server-side data layer: Supabase cache first, SimFin fallback.
 * All functions here run in API routes only (they use SIMFIN_API_KEY).
 */
import { getSupabase } from "./supabase";
import {
  getCompanyByTicker,
  getAllStatements,
  SimFinError,
  type FiscalPeriod,
} from "./simfin";

const CACHE_TTL_MS = 24 * 60 * 60 * 1000; // 24h per spec

export interface CompanyRow {
  id: string;
  ticker: string;
  name: string;
  sector: string | null;
  industry: string | null;
  simfin_id: number | null;
}

export interface FinancialRow {
  id: string;
  company_id: string;
  line_item: string;
  period: FiscalPeriod;
  fiscal_year: number;
  value: number | null;
  is_hardcoded: boolean;
  source_url: string | null;
  updated_at: string;
}

export interface FinancialsResult {
  company: CompanyRow;
  rows: FinancialRow[];
  fromCache: boolean;
  /** Set when SimFin was rate-limited and we served stale cached data instead. */
  warning?: string;
}

/**
 * Find a company in Supabase by ticker; if unknown, look it up on SimFin
 * and insert it. Returns null when the ticker doesn't exist anywhere.
 */
export async function getOrCreateCompany(
  ticker: string
): Promise<CompanyRow | null> {
  const supabase = getSupabase();
  const upper = ticker.trim().toUpperCase();

  const { data: existing, error: selectError } = await supabase
    .from("companies")
    .select("id, ticker, name, sector, industry, simfin_id")
    .eq("ticker", upper)
    .maybeSingle();
  if (selectError) throw new Error(`Supabase select failed: ${selectError.message}`);
  if (existing) return existing as CompanyRow;

  const simfin = await getCompanyByTicker(upper);
  if (!simfin) return null;

  const { data: inserted, error: insertError } = await supabase
    .from("companies")
    .upsert(
      {
        ticker: simfin.ticker,
        name: simfin.name,
        sector: simfin.sector,
        industry: simfin.industry,
        simfin_id: simfin.simfinId,
      },
      { onConflict: "ticker" }
    )
    .select("id, ticker, name, sector, industry, simfin_id")
    .single();
  if (insertError) throw new Error(`Supabase insert failed: ${insertError.message}`);

  return inserted as CompanyRow;
}

/**
 * Get all financial line items for (ticker, period, fiscalYear).
 * Serves from Supabase when the cache is younger than 24h; otherwise fetches
 * from SimFin and upserts. If SimFin is rate-limited, stale cache is served
 * with a warning rather than failing.
 */
export async function getFinancials(
  ticker: string,
  period: FiscalPeriod,
  fiscalYear: number
): Promise<FinancialsResult | null> {
  const supabase = getSupabase();

  const company = await getOrCreateCompany(ticker);
  if (!company) return null;

  const { data: cached, error: cacheError } = await supabase
    .from("financials")
    .select(
      "id, company_id, line_item, period, fiscal_year, value, is_hardcoded, source_url, updated_at"
    )
    .eq("company_id", company.id)
    .eq("period", period)
    .eq("fiscal_year", fiscalYear)
    .order("line_item");
  if (cacheError) throw new Error(`Supabase select failed: ${cacheError.message}`);

  const rows = (cached ?? []) as FinancialRow[];
  const newest = rows.reduce(
    (max, r) => Math.max(max, new Date(r.updated_at).getTime()),
    0
  );
  const isFresh = rows.length > 0 && Date.now() - newest < CACHE_TTL_MS;

  if (isFresh) {
    return { company, rows, fromCache: true };
  }

  // Cache miss or stale → hit SimFin.
  let lineItems;
  try {
    lineItems = await getAllStatements(ticker, period, fiscalYear);
  } catch (err) {
    if (err instanceof SimFinError && err.rateLimited && rows.length > 0) {
      return {
        company,
        rows,
        fromCache: true,
        warning:
          "SimFin rate limit reached — showing cached data that may be older than 24h.",
      };
    }
    throw err;
  }

  if (lineItems.length === 0) {
    // SimFin has nothing for this year/period; return whatever we had.
    return { company, rows, fromCache: rows.length > 0 };
  }

  const upsertPayload = lineItems.map((li) => ({
    company_id: company.id,
    line_item: li.lineItem,
    period: li.period,
    fiscal_year: li.fiscalYear,
    value: li.value,
    is_hardcoded: true,
    source_url: li.sourceUrl,
    updated_at: new Date().toISOString(),
  }));

  // Deduplicate payload by unique constraint key to prevent "ON CONFLICT DO UPDATE cannot affect row a second time"
  const seen = new Set<string>();
  const uniquePayload = [];
  for (const item of upsertPayload) {
    const key = `${item.company_id}|${item.line_item}|${item.period}|${item.fiscal_year}`;
    if (!seen.has(key)) {
      seen.add(key);
      uniquePayload.push(item);
    }
  }

  const { data: upserted, error: upsertError } = await supabase
    .from("financials")
    .upsert(uniquePayload, {
      onConflict: "company_id,line_item,period,fiscal_year",
    })
    .select(
      "id, company_id, line_item, period, fiscal_year, value, is_hardcoded, source_url, updated_at"
    );
  if (upsertError) throw new Error(`Supabase upsert failed: ${upsertError.message}`);

  return {
    company,
    rows: (upserted ?? []) as FinancialRow[],
    fromCache: false,
  };
}
