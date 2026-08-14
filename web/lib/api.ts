// FinClone backend client. All data fetching happens in server components,
// so no CORS setup is needed on the FastAPI side.
export const API_BASE = process.env.FINCLONE_API ?? "http://127.0.0.1:8000";

// BOE DCF, for handing a ticker straight into a new model (QA review Aug 2026,
// DCF #3). DCF accepts ?ticker= to prefill and &build=1 to build on arrival.
export const DCF_BASE = process.env.NEXT_PUBLIC_DCF_BASE ?? "https://dcf.boegroup.com";

export interface CompanySummary {
  ticker: string;
  name: string;
  cik: string;
  sector: string | null;
  source?: "sec" | "baseline";
}

/** How much cross-reference checking a single number has actually had. */
export type ValidationStatus =
  | "agreed"        // compared against the reference source and matched
  | "flagged"       // compared and disputed — open in the review queue
  | "not_compared"  // the reference source doesn't carry this concept
  | "not_checked";  // never cross-referenced

export interface Fact {
  concept: string;
  xbrl_tag: string;
  value: number;
  unit: string;
  fiscal_year: number;
  fiscal_period: string;
  end_date: string;
  form: string;
  filed_date: string;
  derived: boolean;
  source_url: string;
  validation_status: ValidationStatus;
  last_validated: string | null;
}

export interface PeerMetric {
  key: string;
  label: string;
  company: number;
  median: number;
  percentile: number;
  sample: number;
}

export interface PeerRow {
  ticker: string;
  name: string;
  fiscal_year: number | null;
  revenue: number | null;
  [metric: string]: string | number | null;
}

export interface PeerBenchmark {
  sector: string | null;
  peer_count: number;
  company?: PeerRow;
  metrics: PeerMetric[];
  peers: PeerRow[];
  reason?: string;
}

export interface ValidationFlag {
  concept: string;
  fiscal_year: number;
  our_value: number;
  reference_value: number;
  variance: number;
  resolved: boolean;
}

export interface Kpi {
  name: string;
  value: number | null;
  value_text: string;
  unit: string;
  period: string;
  source_quote: string;
  form: string;
  filed_date: string;
  source_url: string;
}

export async function getJSON<T>(path: string): Promise<T | null> {
  try {
    // Service key for API-key-enforced deployments (FINCLONE_REQUIRE_API_KEY);
    // unset in local dev, where the API is open.
    const key = process.env.FINCLONE_API_KEY;
    const res = await fetch(`${API_BASE}${path}`, {
      cache: "no-store",
      headers: key ? { "X-API-Key": key } : undefined,
    });
    if (!res.ok) {
      // Visible in the web dev-server terminal — the UI shows a friendly
      // fallback, so this log is the only place the real cause appears.
      console.error(`[api] ${res.status} ${res.statusText} from ${API_BASE}${path}`);
      return null;
    }
    return (await res.json()) as T;
  } catch (e) {
    console.error(`[api] unreachable: ${API_BASE}${path} —`,
      e instanceof Error ? e.message : e);
    return null;
  }
}
