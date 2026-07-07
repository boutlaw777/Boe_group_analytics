/**
 * SimFin API integration layer — SERVER-SIDE ONLY.
 *
 * NOTE: SimFin retired its v1/v2 APIs. All requests go to the current v3 API:
 *   https://backend.simfin.com/api/v3
 * Free-tier keys work against v3. Docs: https://simfin.readme.io/
 *
 * v3 "compact" responses come back as { columns: string[], data: any[][] } —
 * we zip those into plain records so the rest of the app never sees the raw shape.
 */

const SIMFIN_BASE_URL = "https://backend.simfin.com/api/v3";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export type StatementType = "PL" | "BS" | "CF" | "DERIVED";
export type FiscalPeriod = "FY" | "Q1" | "Q2" | "Q3" | "Q4";

export interface SimFinCompany {
  simfinId: number;
  ticker: string;
  name: string;
  sector: string | null;
  industry: string | null;
}

export interface LineItemValue {
  lineItem: string;
  period: FiscalPeriod;
  fiscalYear: number;
  value: number | null;
  /**
   * Link to the source filing when SimFin provides one, else the SimFin
   * company page. GRANULARITY: SimFin returns ONE source per statement/period
   * (an SEC EDGAR filing *index* page, possibly a later restating filing) —
   * every line item on that statement shares it. Value-level traceability to
   * the exact disclosure is NOT available from SimFin.
   */
  sourceUrl: string;
}

export class SimFinError extends Error {
  constructor(
    message: string,
    public readonly status: number,
    /** true for 429s — callers should surface a friendly "rate limited" message */
    public readonly rateLimited: boolean = false
  ) {
    super(message);
    this.name = "SimFinError";
  }
}

// ---------------------------------------------------------------------------
// Core fetch helper
// ---------------------------------------------------------------------------

function getApiKey(): string {
  const key = process.env.SIMFIN_API_KEY;
  if (!key) {
    throw new SimFinError(
      "SIMFIN_API_KEY is not set. Add it to .env.local (server-side only).",
      500
    );
  }
  return key;
}

async function simfinFetch<T>(
  path: string,
  params: Record<string, string>
): Promise<T> {
  const url = new URL(`${SIMFIN_BASE_URL}${path}`);
  for (const [k, v] of Object.entries(params)) {
    url.searchParams.set(k, v);
  }

  const res = await fetch(url.toString(), {
    headers: {
      Authorization: getApiKey(),
      Accept: "application/json",
    },
    // Data is cached in Supabase for 24h; don't let Next.js cache on top of that.
    cache: "no-store",
  });

  if (res.status === 429) {
    throw new SimFinError(
      "SimFin rate limit reached (free tier). Try again in a minute — cached data will still be served.",
      429,
      true
    );
  }
  if (res.status === 401 || res.status === 403) {
    throw new SimFinError("SimFin API key is invalid or unauthorized.", res.status);
  }
  if (!res.ok) {
    const body = await res.text().catch(() => "");
    throw new SimFinError(
      `SimFin request failed (${res.status}): ${body.slice(0, 200)}`,
      res.status
    );
  }

  return (await res.json()) as T;
}

// ---------------------------------------------------------------------------
// Compact-format helpers
// ---------------------------------------------------------------------------

interface CompactTable {
  columns: string[];
  data: unknown[][];
}

/** Zip a compact { columns, data } table into an array of records. */
function zipCompact(table: CompactTable): Record<string, unknown>[] {
  if (!table?.columns || !Array.isArray(table.data)) return [];
  return table.data.map((row) => {
    const record: Record<string, unknown> = {};
    table.columns.forEach((col, i) => {
      record[col] = row[i];
    });
    return record;
  });
}

/** Columns in statement responses that are metadata, not financial line items. */
const META_COLUMNS = new Set([
  "Fiscal Period",
  "Fiscal Year",
  "Report Date",
  "Publish Date",
  "Restated Date",
  "Source",
  "TTM",
  "Value Check",
  "Currency",
]);

function pickString(rec: Record<string, unknown>, keys: string[]): string | null {
  for (const key of keys) {
    const v = rec[key];
    if (typeof v === "string" && v.length > 0) return v;
  }
  return null;
}

function pickNumber(rec: Record<string, unknown>, keys: string[]): number | null {
  for (const key of keys) {
    const v = rec[key];
    if (typeof v === "number" && Number.isFinite(v)) return v;
  }
  return null;
}

// ---------------------------------------------------------------------------
// Public API
// ---------------------------------------------------------------------------

/**
 * Look up a company's general info by ticker.
 * Returns null if SimFin doesn't know the ticker.
 */
export async function getCompanyByTicker(
  ticker: string
): Promise<SimFinCompany | null> {
  const upper = ticker.trim().toUpperCase();

  const payload = await simfinFetch<CompactTable>("/companies/general/compact", {
    ticker: upper,
  });

  const rows = zipCompact(payload);
  if (rows.length === 0) return null;

  const rec = rows[0];
  const simfinId = pickNumber(rec, ["id", "SimFinId", "simId"]);
  const name = pickString(rec, ["name", "Company Name", "companyName"]);
  if (simfinId === null || !name) return null;

  return {
    simfinId,
    ticker: pickString(rec, ["ticker", "Ticker"]) ?? upper,
    name,
    sector: pickString(rec, ["sectorName", "Sector", "sector"]),
    industry: pickString(rec, ["industryName", "Industry", "industry"]),
  };
}

/**
 * Fetch a financial statement for a ticker and normalize every line item
 * into flat LineItemValue rows, ready to upsert into the `financials` table.
 *
 * @param ticker    e.g. "AAPL"
 * @param statement "PL" | "BS" | "CF" | "DERIVED"
 * @param period    "FY" for annual, or "Q1".."Q4"
 * @param fiscalYear e.g. 2023
 */
export async function getFinancialStatement(
  ticker: string,
  statement: StatementType,
  period: FiscalPeriod,
  fiscalYear: number
): Promise<LineItemValue[]> {
  const upper = ticker.trim().toUpperCase();

  // v3 statements response: an array (one entry per company), each with a
  // `statements` array of compact tables — one per requested statement type.
  const payload = await simfinFetch<
    Array<{
      ticker?: string;
      statements?: Array<{ statement: string } & CompactTable>;
    }>
  >("/companies/statements/compact", {
    ticker: upper,
    statements: statement,
    period,
    fyear: String(fiscalYear),
  });

  const company = Array.isArray(payload) ? payload[0] : undefined;
  const table = company?.statements?.find((s) => s.statement === statement)
    ?? company?.statements?.[0];
  if (!table) return [];

  const results: LineItemValue[] = [];
  const fallbackSourceUrl = `https://app.simfin.com/companies/${encodeURIComponent(upper)}`;

  for (const rec of zipCompact(table)) {
    const recPeriod =
      (pickString(rec, ["Fiscal Period"]) as FiscalPeriod | null) ?? period;
    const recYear = pickNumber(rec, ["Fiscal Year"]) ?? fiscalYear;
    // SimFin's "Source" column links to the underlying filing when available.
    const sourceUrl = pickString(rec, ["Source"]) ?? fallbackSourceUrl;

    for (const [column, raw] of Object.entries(rec)) {
      if (META_COLUMNS.has(column)) continue;
      const value =
        typeof raw === "number" && Number.isFinite(raw) ? raw : null;
      // Skip non-numeric junk columns, but keep genuine null values so we
      // know the item exists on the statement.
      if (raw !== null && value === null) continue;

      results.push({
        lineItem: column,
        period: recPeriod,
        fiscalYear: recYear,
        value,
        sourceUrl,
      });
    }
  }

  return results;
}

/**
 * Convenience: fetch multiple statements (PL + BS + CF + DERIVED) for one
 * ticker/period/year in sequence, tolerating individual failures so one bad
 * statement doesn't sink the whole request.
 */
export async function getAllStatements(
  ticker: string,
  period: FiscalPeriod,
  fiscalYear: number,
  statements: StatementType[] = ["PL", "BS", "CF", "DERIVED"]
): Promise<LineItemValue[]> {
  const all: LineItemValue[] = [];
  for (const st of statements) {
    try {
      all.push(...(await getFinancialStatement(ticker, st, period, fiscalYear)));
    } catch (err) {
      // Rate limits should bubble up so the caller can tell the user.
      if (err instanceof SimFinError && err.rateLimited) throw err;
      console.error(`SimFin ${st} fetch failed for ${ticker}:`, err);
    }
  }
  return all;
}
