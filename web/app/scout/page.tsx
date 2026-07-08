import Link from "next/link";
import { API_BASE, getJSON } from "@/lib/api";
import { fmtMoney } from "@/lib/format";
import { WatchlistActions } from "@/components/WatchlistActions";

interface ScoutResult {
  ticker: string;
  name: string;
  sector: string | null;
  fiscal_year: number;
  metrics: Record<string, number>;
}

interface ScoutResponse {
  query: string;
  interpretation: {
    sector: string | null;
    filters: { metric: string; op: string; value: number }[];
    sort_by: string | null;
    descending: boolean;
  };
  results: ScoutResult[];
}

interface Datapoint {
  ticker: string;
  company: string;
  kpi: string;
  latest_period: string;
  latest_value: string;
  source_url: string;
}

const PCT_METRICS = /(_growth|_margin|^roe)$/;

function fmtMetric(name: string, value: number): string {
  if (PCT_METRICS.test(name)) return `${(value * 100).toFixed(1)}%`;
  if (name === "eps_diluted") return value.toFixed(2);
  return fmtMoney(value);
}

export default async function ScoutPage({
  searchParams,
}: {
  searchParams: Promise<{ q?: string; dp?: string }>;
}) {
  const { q, dp } = await searchParams;
  const screen = q ? await getJSON<ScoutResponse>(`/scout?q=${encodeURIComponent(q)}`) : null;
  const datapoints = dp
    ? await getJSON<Datapoint[]>(`/scout/datapoints?q=${encodeURIComponent(dp)}`)
    : null;

  const columns = screen
    ? [...new Set(screen.results.flatMap((r) => Object.keys(r.metrics)))]
    : [];

  return (
    <>
      <h1>Scout</h1>
      <p className="muted">
        Screen companies in plain English. Your question becomes a structured
        filter; every number comes from the database, not the model.
      </p>

      <form className="search-row" method="get" action="/scout">
        <input
          name="q"
          defaultValue={q ?? ""}
          style={{ maxWidth: 560 }}
          placeholder='e.g. companies with revenue growth over 10% and net margin over 25%'
        />
        <button type="submit">Screen</button>
      </form>

      {q && !screen && (
        <div className="notice">
          Scout is temporarily unavailable — please try again in a moment.
        </div>
      )}

      {screen && (
        <>
          <p className="muted">
            Interpreted as:{" "}
            {screen.interpretation.sector && <>sector = <b>{screen.interpretation.sector}</b>; </>}
            {screen.interpretation.filters.length > 0
              ? screen.interpretation.filters.map((f, i) => (
                  <span key={i}>
                    <b>{f.metric} {f.op} {PCT_METRICS.test(f.metric) ? `${f.value * 100}%` : f.value.toLocaleString()}</b>
                    {i < screen.interpretation.filters.length - 1 ? " and " : ""}
                  </span>
                ))
              : "no filters"}
            {screen.interpretation.sort_by && <> — sorted by <b>{screen.interpretation.sort_by}</b></>}
          </p>

          {screen.results.length === 0 ? (
            <p className="muted">No companies in the database match this screen.</p>
          ) : (
            <div className="card" style={{ overflowX: "auto", padding: 0 }}>
              <table>
                <thead>
                  <tr>
                    <th>Company</th>
                    <th>FY</th>
                    {columns.map((c) => <th key={c}>{c.replaceAll("_", " ")}</th>)}
                  </tr>
                </thead>
                <tbody>
                  {screen.results.map((r) => (
                    <tr key={r.ticker}>
                      <td>
                        <Link href={`/company/${r.ticker}`}><b>{r.ticker}</b></Link>{" "}
                        <span className="muted">{r.name}</span>
                      </td>
                      <td className="num">{r.fiscal_year}</td>
                      {columns.map((c) => (
                        <td key={c} className="num">
                          {r.metrics[c] !== undefined ? fmtMetric(c, r.metrics[c]) : "—"}
                        </td>
                      ))}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
          {screen.results.length > 0 && (
            <WatchlistActions
              apiBase={API_BASE}
              tickers={screen.results.map((r) => r.ticker)}
            />
          )}
        </>
      )}

      <h2>Data point search</h2>
      <p className="muted">
        Find which companies report a specific niche metric (searches the
        LLM-extracted KPI names).
      </p>
      <form className="search-row" method="get" action="/scout">
        <input name="dp" defaultValue={dp ?? ""} placeholder="e.g. services revenue, RevPAR, wafer" />
        <button type="submit">Find</button>
      </form>

      {dp && datapoints && datapoints.length === 0 && (
        <p className="muted">No companies report a KPI matching “{dp}”.</p>
      )}
      {datapoints && datapoints.length > 0 && (
        <div className="card" style={{ overflowX: "auto", padding: 0 }}>
          <table>
            <thead>
              <tr>
                <th>Company</th>
                <th style={{ textAlign: "left" }}>KPI</th>
                <th>Latest period</th>
                <th>Latest value</th>
              </tr>
            </thead>
            <tbody>
              {datapoints.map((d, i) => (
                <tr key={i}>
                  <td><Link href={`/company/${d.ticker}`}><b>{d.ticker}</b></Link> <span className="muted">{d.company}</span></td>
                  <td style={{ textAlign: "left" }}>{d.kpi}</td>
                  <td className="num">{d.latest_period}</td>
                  <td className="num">
                    <a className="num" href={d.source_url} target="_blank" rel="noreferrer">{d.latest_value}</a>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </>
  );
}
