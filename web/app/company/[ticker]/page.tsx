import { notFound } from "next/navigation";
import { API_BASE, getJSON, type CompanySummary, type Fact, type Kpi, type ValidationFlag } from "@/lib/api";
import { CONCEPT_LABELS, PLAIN_CONCEPTS, epsSplitFactor, fmtMoney, fmtPlain } from "@/lib/format";
import { DatasheetBuilder } from "@/components/DatasheetBuilder";

const CONCEPT_NAME = new Map(CONCEPT_LABELS);

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

  const [company, facts, kpis, templates, flags] = await Promise.all([
    getJSON<Detail>(`/companies/${t}`),
    getJSON<Fact[]>(`/companies/${t}/financials?point_in_time=latest`),
    getJSON<Kpi[]>(`/companies/${t}/kpis`),
    getJSON<{ id: number; name: string }[]>("/templates"),
    getJSON<ValidationFlag[]>(`/companies/${t}/validation`),
  ]);
  if (!company) notFound();

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
        <a className="btn" href={`${API_BASE}/companies/${t}/datasheet?period=annual`}>
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
                    return (
                      <td key={y} className="num">
                        <a
                          className={`num${f.derived ? " derived" : ""}`}
                          href={f.source_url}
                          target="_blank"
                          rel="noreferrer"
                          title={
                            f.form === "SimFin"
                              ? "SimFin baseline (standardized data) — click for the company's SEC filing index. Run the SEC ingest for filing-level audit links."
                              : `${f.form} filed ${f.filed_date}${f.derived ? " (derived Q4 value)" : ""}${splitNote}`
                          }
                        >
                          {text}
                        </a>
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
