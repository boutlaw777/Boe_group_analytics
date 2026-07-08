"use client";

import Link from "next/link";
import { useMemo, useState } from "react";
import type { CompanySummary } from "@/lib/api";

const PAGE = 60;

export default function CompanyGrid({ companies }: { companies: CompanySummary[] }) {
  const [query, setQuery] = useState("");
  const [shown, setShown] = useState(PAGE);

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    if (!q) return companies;
    return companies.filter(
      (c) =>
        c.ticker.toLowerCase().includes(q) ||
        c.name.toLowerCase().includes(q) ||
        (c.sector ?? "").toLowerCase().includes(q),
    );
  }, [companies, query]);

  // SEC-extracted companies first — they carry the filing-level audit trail.
  const ordered = useMemo(
    () =>
      [...filtered].sort((a, b) =>
        a.source === b.source ? a.ticker.localeCompare(b.ticker) : a.source === "sec" ? -1 : 1,
      ),
    [filtered],
  );
  const visible = ordered.slice(0, shown);

  return (
    <>
      <div className="search-row" style={{ marginBottom: 16 }}>
        <input
          value={query}
          onChange={(e) => {
            setQuery(e.target.value);
            setShown(PAGE);
          }}
          placeholder="Filter by ticker, name, or sector…"
          aria-label="Filter companies"
        />
        <span className="muted" style={{ alignSelf: "center", whiteSpace: "nowrap" }}>
          {filtered.length.toLocaleString()} compan{filtered.length === 1 ? "y" : "ies"}
        </span>
      </div>

      <div className="company-grid">
        {visible.map((c) => (
          <Link key={c.ticker} href={`/company/${c.ticker}`} className="company-card">
            <div className="ticker">
              {c.ticker}
              {c.source === "baseline" && (
                <span
                  title="Standardized baseline data (SimFin). Run the SEC ingest for filing-level audit links."
                  style={{
                    marginLeft: 8,
                    fontSize: 10,
                    fontWeight: 600,
                    letterSpacing: 0.5,
                    color: "#8a6d1a",
                    background: "#faf3dd",
                    border: "1px solid #e8d9a8",
                    borderRadius: 4,
                    padding: "1px 6px",
                    verticalAlign: "middle",
                  }}
                >
                  BASELINE
                </span>
              )}
            </div>
            <div>{c.name}</div>
            <div className="sector">{c.sector ?? "Unclassified"} · CIK {c.cik}</div>
          </Link>
        ))}
      </div>

      {ordered.length > shown && (
        <p style={{ textAlign: "center" }}>
          <button className="btn secondary" onClick={() => setShown(shown + PAGE * 4)}>
            Show more ({(ordered.length - shown).toLocaleString()} remaining)
          </button>
        </p>
      )}
    </>
  );
}
