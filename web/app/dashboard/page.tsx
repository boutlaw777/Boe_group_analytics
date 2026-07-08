import CompanyGrid from "@/components/CompanyGrid";
import SearchBox from "@/components/SearchBox";
import { getJSON, type CompanySummary } from "@/lib/api";

export default async function Dashboard() {
  const companies = await getJSON<CompanySummary[]>("/companies");

  return (
    <>
      <h1>Coverage</h1>
      <p className="muted">
        Companies ingested from SEC EDGAR with full point-in-time history, plus
        a standardized baseline for the rest of the US market. Baseline names
        upgrade to filing-level audit links when their SEC ingest runs.
      </p>
      <SearchBox />

      {companies === null ? (
        <div className="notice">
          The data service isn&apos;t reachable right now — please refresh in a
          moment.
        </div>
      ) : companies.length === 0 ? (
        <div className="notice">
          No companies are covered yet. Coverage appears here as soon as
          filings are ingested.
        </div>
      ) : (
        <CompanyGrid companies={companies} />
      )}
    </>
  );
}
