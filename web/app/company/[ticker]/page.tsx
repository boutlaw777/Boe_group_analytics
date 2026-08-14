import { notFound } from "next/navigation";
import {
  API_BASE, DCF_BASE, getJSON,
  type CompanySummary, type Fact, type Kpi, type PeerBenchmark,
  type ValidationFlag, type ValidationStatus,
} from "@/lib/api";
import { CONCEPT_LABELS, PLAIN_CONCEPTS, epsSplitFactor, fmtMoney, fmtPlain } from "@/lib/format";
import { DatasheetBuilder } from "@/components/DatasheetBuilder";

const CONCEPT_NAME = new Map(CONCEPT_LABELS);

// Per-number validation provenance (QA review Aug 2026, Analytics #3). Shown as
// a small mark beside the value rather than a column, so it reads at a glance
// without pushing eight fiscal years off the side of the table.
//
// "agreed" is deliberately the *only* unmarked state: if every number carried a
// tick, the marks would become wallpaper and the flagged ones would stop
// standing out, which is the one thing this has to achieve.
const VALIDATION_MARK: Record<ValidationStatus, { mark: string; color: string; note: string }> = {
  agreed: { mark: "", color: "", note: "Cross-referenced against the independent reference source and matched" },
  flagged: { mark: "!", color: "#b8860b", note: "Disputed — open in the validation review queue below" },
  not_compared: { mark: "·", color: "#9aa5b1", note: "Not covered by the reference source, so never cross-referenced" },
  not_checked: { mark: "·", color: "#9aa5b1", note: "This company has not been cross-referenced yet" },
};

function fmtPct(value: number): string {
  return `${(value * 100).toFixed(1)}%`;
}

interface Detail extends CompanySummary {
  sic: string | null;
}

export default async function CompanyPage({
  params,
}: {
  params: Promise<{ ticker: string }>;
}) {
  const { ticker } = await params;
  const t = ticker.toUpperCase();

  const [company, facts, kpis, templates, flags, peers] = await Promise.all([
    getJSON<Detail>(`/companies/${t}`),
    getJSON<Fact[]>(`/companies/${t}/financials?point_in_time=latest`),
    getJSON<Kpi[]>(`/companies/${t}/kpis`),
    getJSON<{ id: number; name: string }[]>("/templates"),
    getJSON<ValidationFlag[]>(`/companies/${t}/validation`),
    getJSON<PeerBenchmark>(`/companies/${t}/peers`),
  ]);
  if (!company) notFound();

  // Company-level: every fact carries the same crossref date, so read it once.
  const lastValidated = (facts ?? []).find((f) => f.last_validated)?.last_validated ?? null;

  // Pivot facts into concept x fiscal-year, preferring FY (flows) and falling
  // back to Q4 (year-end balance-sheet instants).
  const byKey = new Map<string, Fact>();
  for (const f of facts ?? []) {
    byKey.set(`${f.concept}|${f.fiscal_year}|${f.fiscal_period}`, f);
  }
  const cellFor = (concept: string, year: number): Fact | undefined =>
    byKey.get(`${concept}|${year}|FY`) ?? byKey.get(`${concept}|${year}|Q4`);
  // Only show fiscal years where at least one displayed line item has a value
  // (a new quarter's filing can tag the upcoming FY before any annual data exists).
  const years = [...new Set((facts ?? []).map((f) => f.fiscal_year))]
    .sort((a, b) => a - b)
    .filter((y) => CONCEPT_LABELS.some(([concept]) => cellFor(concept, y)))
    .slice(-8);
  const rows = CONCEPT_LABELS.filter(([concept]) =>
    years.some((y) => cellFor(concept, y)),
  );

  // Put as-reported EPS on the current (post-split) basis. Reference = the
  // latest year that has both EPS and net income.
  const refYear = [...years].reverse().find(
    (y) => cellFor("eps_diluted", y) && cellFor("net_income", y),
  );
  const epsRef = refYear ? cellFor("eps_diluted", refYear)!.value : 0;
  const niRef = refYear ? cellFor("net_income", refYear)!.value : 0;
  const epsAdjusted = (year: number, raw: number): { value: number; adjusted: boolean } => {
    const ni = cellFor("net_income", year)?.value ?? 0;
    const factor = epsSplitFactor(raw, ni, epsRef, niRef);
    return { value: raw / factor, adjusted: factor !== 1 };
  };
  let anyEpsAdjusted = false;
  const anyBaseline = (facts ?? []).some((f) => f.form === "SimFin");

  return (
    <>
      <h1>
        {company.name} <span className="muted">({company.ticker})</span>
      </h1>
      <p className="muted">
        {company.sector ?? "Unclassified"} · CIK {company.cik}
      </p>

      <p>
        {/* Hand-off into BOE DCF (QA review Aug 2026, DCF #3). Deliberately
            ?ticker= and not &build=1: prefilling saves the re-typing the review
            asked about, while still letting the analyst see the duplicate-model
            warning before a model is created. */}
        <a className="btn" href={`${DCF_BASE}/model/new?ticker=${t}`}
           target="_blank" rel="noreferrer">
          Build DCF Model →
        </a>{" "}
        <a className="btn secondary" href={`${API_BASE}/companies/${t}/datasheet?period=annual`}>
          Download Data Sheet (annual)
        </a>{" "}
        <a className="btn secondary" href={`${API_BASE}/companies/${t}/datasheet?period=quarterly`}>
          Quarterly
        </a>
        {(templates ?? []).map((tpl) => (
          <span key={tpl.id}>
            {" "}
            <a className="btn secondary"
               href={`${API_BASE}/companies/${t}/datasheet?template_id=${tpl.id}`}>
              {tpl.name}
            </a>
          </span>
        ))}
      </p>
      <DatasheetBuilder
        apiBase={API_BASE}
        ticker={t}
        concepts={CONCEPT_LABELS}
        years={years}
      />

      <h2>Financials <span className="muted" style={{ fontSize: 14, fontWeight: 400 }}>(annual · USD, M = millions, B = billions)</span></h2>
      {rows.length === 0 ? (
        <p className="muted">No financial data ingested for this company yet.</p>
      ) : (
        <div className="card" style={{ overflowX: "auto", padding: 0 }}>
          <table>
            <thead>
              <tr>
                <th>Line item</th>
                {years.map((y) => (
                  <th key={y}>FY{y}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {rows.map(([concept, label]) => (
                <tr key={concept}>
                  <td>{label}</td>
                  {years.map((y) => {
                    const f = cellFor(concept, y);
                    if (!f) return <td key={y} className="num">—</td>;
                    let value = f.value;
                    let splitNote = "";
                    if (concept === "eps_diluted") {
                      const adj = epsAdjusted(y, f.value);
                      value = adj.value;
                      if (adj.adjusted) {
                        anyEpsAdjusted = true;
                        splitNote = " (split-adjusted to current share basis)";
                      }
                    }
                    const text = PLAIN_CONCEPTS.has(concept)
                      ? fmtPlain(value)
                      : fmtMoney(value);
                    const validation = VALIDATION_MARK[f.validation_status];
                    const validationNote = validation
                      ? ` · ${validation.note}${f.last_validated ? ` (last checked ${f.last_validated})` : ""}`
                      : "";
                    return (
                      <td key={y} className="num">
                        <a
                          className={`num${f.derived ? " derived" : ""}`}
                          href={f.source_url}
                          target="_blank"
                          rel="noreferrer"
                          title={
                            (f.form === "SimFin"
                              ? "SimFin baseline (standardized data) — click for the company's SEC filing index. Run the SEC ingest for filing-level audit links."
                              : `${f.form} filed ${f.filed_date}${f.derived ? " (derived Q4 value)" : ""}${splitNote}`
                            ) + validationNote
                          }
                        >
                          {text}
                        </a>
                        {validation?.mark && (
                          <span
                            title={validation.note}
                            style={{ color: validation.color, marginLeft: 3, fontWeight: 600 }}
                          >
                            {validation.mark}
                          </span>
                        )}
                      </td>
                    );
                  })}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      <p className="muted">
        {anyBaseline
          ? "This company is covered by standardized baseline data (SimFin); values link to its SEC filing index. Running the SEC ingest upgrades every number to a filing-level audit link."
          : "Blue values link to the SEC filing they were reported in. Italic values are derived (Q4 = FY − Q1 − Q2 − Q3)."}
        {anyEpsAdjusted &&
          " Diluted EPS for pre-split years is adjusted to the current share basis; the linked filing shows the as-reported value."}
      </p>
      <p className="muted">
        {lastValidated
          ? `Cross-referenced against the independent reference source on ${lastValidated}. `
          : "This company has not been cross-referenced against the reference source yet. "}
        Unmarked values were compared and matched;{" "}
        <span style={{ color: "#b8860b", fontWeight: 600 }}>!</span> marks a disputed value
        held in the review queue below;{" "}
        <span style={{ color: "#9aa5b1", fontWeight: 600 }}>·</span> marks a value the
        reference source does not cover, so it has not been independently checked.
      </p>

      {flags && flags.length > 0 && (
        <>
          <h2>Validation review queue</h2>
          <p className="muted">
            Values where our SEC extraction and the independent reference
            source disagree by more than 1% — held for human review, not
            silently published. Differences are usually classification
            conventions (e.g. what counts as long-term debt), not errors.
          </p>
          <div className="card" style={{ overflowX: "auto", padding: 0 }}>
            <table>
              <thead>
                <tr>
                  <th style={{ textAlign: "left" }}>Line item</th>
                  <th>Fiscal year</th>
                  <th>Our value (SEC)</th>
                  <th>Reference value</th>
                  <th>Variance</th>
                  <th>Status</th>
                </tr>
              </thead>
              <tbody>
                {flags.map((f, i) => (
                  <tr key={i}>
                    <td>{CONCEPT_NAME.get(f.concept) ?? f.concept}</td>
                    <td className="num">FY{f.fiscal_year}</td>
                    <td className="num">{fmtMoney(f.our_value)}</td>
                    <td className="num">{fmtMoney(f.reference_value)}</td>
                    <td className="num">{(f.variance * 100).toFixed(1)}%</td>
                    <td className="num">
                      {f.resolved ? "resolved" : (
                        <span style={{ color: "#8a6d1a", background: "#faf3dd",
                                       border: "1px solid #e8d9a8", borderRadius: 4,
                                       padding: "1px 8px", fontSize: 12 }}>
                          open
                        </span>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </>
      )}

      {peers && (
        <>
          <h2>
            Sector benchmarking{" "}
            {peers.sector && (
              <span className="muted" style={{ fontSize: 14, fontWeight: 400 }}>
                ({peers.sector} · {peers.peer_count} peers)
              </span>
            )}
          </h2>
          {peers.metrics.length === 0 ? (
            <p className="muted">
              {peers.reason ?? "No peer comparison is available for this company yet."}
            </p>
          ) : (
            <>
              <p className="muted">
                Latest reported fiscal year against sector peers. Percentile is this
                company&apos;s rank across every peer carrying that metric, not just the
                ones listed below.
              </p>
              <div className="card" style={{ overflowX: "auto", padding: 0 }}>
                <table>
                  <thead>
                    <tr>
                      <th style={{ textAlign: "left" }}>Metric</th>
                      <th>{company.ticker}</th>
                      <th>Sector median</th>
                      <th>Percentile</th>
                      <th>Peers with data</th>
                    </tr>
                  </thead>
                  <tbody>
                    {peers.metrics.map((m) => (
                      <tr key={m.key}>
                        <td>{m.label}</td>
                        <td className="num"><strong>{fmtPct(m.company)}</strong></td>
                        <td className="num">{fmtPct(m.median)}</td>
                        <td className="num">{m.percentile.toFixed(0)}th</td>
                        <td className="num">{m.sample}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>

              <div className="card" style={{ overflowX: "auto", padding: 0, marginTop: 14 }}>
                <table>
                  <thead>
                    <tr>
                      <th style={{ textAlign: "left" }}>Peer</th>
                      <th>FY</th>
                      {peers.metrics.map((m) => (
                        <th key={m.key}>{m.label}</th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {peers.peers.map((p) => (
                      <tr key={p.ticker}>
                        <td>
                          <a href={`/company/${p.ticker}`}>{p.ticker}</a>{" "}
                          <span className="muted">{p.name}</span>
                        </td>
                        <td className="num">{p.fiscal_year ?? "—"}</td>
                        {peers.metrics.map((m) => {
                          const v = p[m.key];
                          return (
                            <td key={m.key} className="num">
                              {typeof v === "number" ? fmtPct(v) : "—"}
                            </td>
                          );
                        })}
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </>
          )}
        </>
      )}

      <h2>Industry KPIs</h2>
      {!kpis || kpis.length === 0 ? (
        <p className="muted">
          No industry KPIs are available for this company yet. They appear here
          automatically once our extraction pipeline has processed its latest
          filings.
        </p>
      ) : (
        <div className="card" style={{ overflowX: "auto", padding: 0 }}>
          <table>
            <thead>
              <tr>
                <th>KPI</th>
                <th>Period</th>
                <th>Value</th>
                <th style={{ textAlign: "left" }}>Source quote</th>
              </tr>
            </thead>
            <tbody>
              {kpis.map((k, i) => (
                <tr key={i}>
                  <td>{k.name}</td>
                  <td className="num">{k.period}</td>
                  <td className="num">
                    <a className="num" href={k.source_url} target="_blank" rel="noreferrer">
                      {k.value_text}
                    </a>
                  </td>
                  <td className="quote">“{k.source_quote}”</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </>
  );
}
