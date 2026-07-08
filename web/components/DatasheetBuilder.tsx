"use client";
import { useState } from "react";

const QUARTERS = ["Q1", "Q2", "Q3", "Q4"] as const;

export function DatasheetBuilder({
  apiBase,
  ticker,
  concepts,
  years,
}: {
  apiBase: string;
  ticker: string;
  concepts: [string, string][]; // [canonical concept, label]
  years: number[]; // ascending fiscal years with data
}) {
  const [open, setOpen] = useState(false);
  const [period, setPeriod] = useState<"annual" | "quarterly">("annual");
  const [selected, setSelected] = useState<Set<string>>(new Set(concepts.map(([c]) => c)));
  const [yearFrom, setYearFrom] = useState<number>(years[0] ?? 0);
  const [yearTo, setYearTo] = useState<number>(years[years.length - 1] ?? 0);
  const [quarters, setQuarters] = useState<Set<string>>(new Set(QUARTERS));

  const allSelected = selected.size === concepts.length;
  const toggleConcept = (c: string) => {
    const next = new Set(selected);
    if (next.has(c)) next.delete(c);
    else next.add(c);
    setSelected(next);
  };
  const toggleQuarter = (q: string) => {
    const next = new Set(quarters);
    if (next.has(q)) next.delete(q);
    else next.add(q);
    setQuarters(next);
  };

  const buildUrl = () => {
    const params = new URLSearchParams({ period });
    if (!allSelected && selected.size > 0) params.set("concepts", [...selected].join(","));
    if (yearFrom !== years[0]) params.set("year_from", String(yearFrom));
    if (yearTo !== years[years.length - 1]) params.set("year_to", String(yearTo));
    if (period === "quarterly" && quarters.size < 4 && quarters.size > 0)
      params.set("quarters", [...quarters].join(","));
    return `${apiBase}/companies/${ticker}/datasheet?${params}`;
  };

  if (!open) {
    return (
      <a className="btn secondary" href="#" onClick={(e) => { e.preventDefault(); setOpen(true); }}>
        Customize sheet…
      </a>
    );
  }

  return (
    <div className="card" style={{ marginTop: 12, padding: 16 }}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "baseline" }}>
        <h3 style={{ margin: 0 }}>Build your Data Sheet</h3>
        <a href="#" className="muted" onClick={(e) => { e.preventDefault(); setOpen(false); }}>close</a>
      </div>

      <div style={{ display: "flex", gap: 24, flexWrap: "wrap", marginTop: 12 }}>
        <div>
          <div style={{ fontWeight: 600, fontSize: 13, marginBottom: 6 }}>Period</div>
          <label style={{ display: "block", fontSize: 13 }}>
            <input type="radio" checked={period === "annual"} onChange={() => setPeriod("annual")} /> Annual
          </label>
          <label style={{ display: "block", fontSize: 13 }}>
            <input type="radio" checked={period === "quarterly"} onChange={() => setPeriod("quarterly")} /> Quarterly
          </label>
          {period === "quarterly" && (
            <div style={{ marginTop: 6 }}>
              {QUARTERS.map((q) => (
                <label key={q} style={{ display: "inline-block", marginRight: 10, fontSize: 13 }}>
                  <input type="checkbox" checked={quarters.has(q)} onChange={() => toggleQuarter(q)} /> {q}
                </label>
              ))}
            </div>
          )}
        </div>

        <div>
          <div style={{ fontWeight: 600, fontSize: 13, marginBottom: 6 }}>Fiscal years</div>
          <select value={yearFrom} onChange={(e) => setYearFrom(Number(e.target.value))}>
            {years.map((y) => (
              <option key={y} value={y} disabled={y > yearTo}>{y}</option>
            ))}
          </select>{" "}
          to{" "}
          <select value={yearTo} onChange={(e) => setYearTo(Number(e.target.value))}>
            {years.map((y) => (
              <option key={y} value={y} disabled={y < yearFrom}>{y}</option>
            ))}
          </select>
        </div>

        <div style={{ minWidth: 220 }}>
          <div style={{ fontWeight: 600, fontSize: 13, marginBottom: 6 }}>
            Line items{" "}
            <a
              href="#"
              style={{ fontWeight: 400 }}
              onClick={(e) => {
                e.preventDefault();
                setSelected(allSelected ? new Set() : new Set(concepts.map(([c]) => c)));
              }}
            >
              ({allSelected ? "clear all" : "select all"})
            </a>
          </div>
          <div style={{ columns: 2, fontSize: 13 }}>
            {concepts.map(([c, label]) => (
              <label key={c} style={{ display: "block", breakInside: "avoid" }}>
                <input type="checkbox" checked={selected.has(c)} onChange={() => toggleConcept(c)} /> {label}
              </label>
            ))}
          </div>
        </div>
      </div>

      <p style={{ marginBottom: 0 }}>
        <a
          className="btn"
          href={selected.size > 0 ? buildUrl() : undefined}
          aria-disabled={selected.size === 0}
          style={selected.size === 0 ? { opacity: 0.5, pointerEvents: "none" } : undefined}
        >
          Download custom sheet
        </a>{" "}
        {selected.size === 0 && <span className="muted">select at least one line item</span>}
      </p>
    </div>
  );
}
