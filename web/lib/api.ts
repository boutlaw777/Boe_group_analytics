// FinClone backend client. All data fetching happens in server components,
// so no CORS setup is needed on the FastAPI side.
export const API_BASE = process.env.FINCLONE_API ?? "http://127.0.0.1:8000";

export interface CompanySummary {
  ticker: string;
  name: string;
  cik: string;
  sector: string | null;
  source?: "sec" | "baseline";
}

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
