import Link from "next/link";
import { API_BASE } from "@/lib/api";

export const metadata = {
  title: "Developer API — BOE Analytics",
  description: "REST API reference: companies, financials, KPIs, validation, data sheets",
};

const mono: React.CSSProperties = {
  fontFamily: "ui-monospace, SFMono-Regular, Menlo, Consolas, monospace",
  fontSize: 13,
};

const codeBlock: React.CSSProperties = {
  ...mono,
  display: "block",
  background: "#0e2233",
  color: "#d9e8f5",
  borderRadius: 8,
  padding: "14px 16px",
  overflowX: "auto",
  whiteSpace: "pre",
  lineHeight: 1.55,
};

const ENDPOINTS = [
  { method: "GET", path: "/companies", text: "All covered companies with ticker, name, CIK, sector, and whether coverage is SEC-extracted or baseline." },
  { method: "GET", path: "/companies/{ticker}", text: "One company's identity: ticker, name, CIK, SIC code, sector." },
  { method: "GET", path: "/companies/{ticker}/financials", text: "Time series of financial facts. Filter with concept, fiscal_year, fiscal_period (Q1–Q4/FY), and point_in_time=latest|original|all for restatement vintages." },
  { method: "GET", path: "/companies/{ticker}/kpis", text: "LLM-extracted niche KPIs (backlog, RPOs, segment metrics…) with the verbatim filing sentence and source link for each." },
  { method: "GET", path: "/companies/{ticker}/validation", text: "Cross-reference review queue: values that disagree with the independent source by more than 1%." },
  { method: "GET", path: "/companies/{ticker}/datasheet", text: "Auditable Excel model (.xlsx). Supports period=annual|quarterly, concepts, year_from/year_to, quarters, and template_id for custom layouts." },
  { method: "GET", path: "/datasheets?tickers=A,B,C", text: "Bulk data-sheet download for up to 50 tickers as a single .zip with a manifest." },
  { method: "GET", path: "/scout?q=…", text: "Natural-language screen. Returns the structured interpretation plus matching companies with computed metrics." },
  { method: "GET", path: "/scout/datapoints?q=…", text: "Data-point search: which companies report a given niche KPI." },
  { method: "GET|POST|DELETE", path: "/templates", text: "Model Creation Platform: save, list, and delete custom sheet layouts (row order + custom formula lines)." },
];

export default function DevelopersPage() {
  return (
    <>
      <section className="hero" style={{ paddingBottom: 8 }}>
        <h1 className="hero-title" style={{ fontSize: 40 }}>Developer API</h1>
        <p className="hero-sub">
          The same validated fundamentals that power this site, as clean JSON —
          with the SEC audit URL on every number. Interactive Swagger docs are
          served by the API itself at{" "}
          <a href={`${API_BASE}/docs`} target="_blank" rel="noreferrer" style={mono}>
            {API_BASE}/docs
          </a>.
        </p>
        <p>
          <Link href="/developers/portal" className="btn hero-btn">
            Sign in / create a free API key
          </Link>
        </p>
      </section>

      <section>
        <h2>Quick start</h2>
        <code style={codeBlock}>
{`curl -H "X-API-Key: YOUR_KEY" \\
  "${API_BASE}/companies/GOOGL/financials?concept=revenue&point_in_time=latest"

[
  {
    "concept": "revenue",
    "xbrl_tag": "RevenueFromContractWithCustomerExcludingAssessedTax",
    "value": 402836000000.0,
    "unit": "USD",
    "fiscal_year": 2025,
    "fiscal_period": "FY",
    "end_date": "2025-12-31",
    "form": "10-K",
    "filed_date": "2026-02-05",
    "derived": false,
    "source_url": "https://www.sec.gov/Archives/edgar/data/1652044/..."
  }
]`}
        </code>
        <p className="muted" style={{ marginTop: 10 }}>
          Every fact carries its XBRL tag, form type, filing date, and a{" "}
          <span style={mono}>source_url</span> straight to the SEC document —
          the audit trail is part of the payload, not an afterthought.
        </p>
      </section>

      <section>
        <h2>Endpoints</h2>
        <div className="card" style={{ padding: 0 }}>
          <table>
            <thead>
              <tr>
                <th style={{ textAlign: "left", width: 340 }}>Endpoint</th>
                <th style={{ textAlign: "left" }}>Returns</th>
              </tr>
            </thead>
            <tbody>
              {ENDPOINTS.map((e) => (
                <tr key={e.path}>
                  <td style={{ textAlign: "left", verticalAlign: "top" }}>
                    <span style={{ ...mono, color: "var(--navy)" }}>
                      <b>{e.method}</b> {e.path}
                    </span>
                  </td>
                  <td style={{ textAlign: "left" }} className="muted">{e.text}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>

      <section className="two-col">
        <div>
          <h2>Authentication</h2>
          <p className="muted" style={{ lineHeight: 1.6 }}>
            Pass your key in the <span style={mono}>X-API-Key</span> header —
            all JSON endpoints require one. Data-sheet downloads (single and
            bulk) are public, since download links can&apos;t carry headers.
            Keys are hashed at rest and can be revoked at any time; a missing,
            revoked, or unknown key gets <span style={mono}>401</span>.
          </p>
          <p className="muted" style={{ lineHeight: 1.6 }}>
            Get a free-tier key instantly in the{" "}
            <Link href="/developers/portal">developer portal</Link> — sign up,
            mint up to two keys, and track your usage. For pro or enterprise
            volume, email{" "}
            <a href="mailto:mohsin@boegroup.com" style={mono}>mohsin@boegroup.com</a>.
          </p>
        </div>
        <div>
          <h2>Rate limits</h2>
          <div className="card" style={{ padding: 0 }}>
            <table>
              <thead>
                <tr>
                  <th style={{ textAlign: "left" }}>Tier</th>
                  <th className="num">Requests / minute</th>
                </tr>
              </thead>
              <tbody>
                <tr><td style={{ textAlign: "left" }}>Free</td><td className="num">60</td></tr>
                <tr><td style={{ textAlign: "left" }}>Pro</td><td className="num">600</td></tr>
                <tr><td style={{ textAlign: "left" }}>Enterprise</td><td className="num">6,000</td></tr>
              </tbody>
            </table>
          </div>
          <p className="muted" style={{ marginTop: 10, lineHeight: 1.6 }}>
            Limits use a 60-second sliding window per key. Exceeding your tier
            returns <span style={mono}>429</span> with the retry time in the
            message.
          </p>
        </div>
      </section>

      <section className="cta-panel">
        <h2>Point-in-time by design.</h2>
        <p style={{ maxWidth: 720, margin: "0 auto" }}>
          <span style={mono}>point_in_time=latest</span> gives current
          (post-restatement) values, <span style={mono}>original</span> gives
          as-first-reported vintages, and <span style={mono}>all</span> returns
          every vintage — so backtests see the numbers the market saw at the
          time.
        </p>
        <p style={{ marginTop: 18 }}>
          <Link href="/developers/portal" className="btn hero-btn">
            Create a free API key
          </Link>{" "}
          <Link href="/dashboard" className="btn secondary hero-btn">Browse coverage</Link>
        </p>
      </section>
    </>
  );
}
