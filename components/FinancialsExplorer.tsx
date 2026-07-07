"use client";

import { Suspense, useState } from "react";
import { useSearchParams } from "next/navigation";
import { useQuery } from "@tanstack/react-query";

const CURRENT_YEAR = new Date().getFullYear();
const YEARS = Array.from({ length: 10 }, (_, i) => CURRENT_YEAR - i);
const PERIODS = ["FY", "Q1", "Q2", "Q3", "Q4"] as const;

interface Company {
  id: string;
  ticker: string;
  name: string;
  sector: string | null;
  industry: string | null;
}

interface FinancialRow {
  id: string;
  line_item: string;
  period: string;
  fiscal_year: number;
  value: number | null;
  is_hardcoded: boolean;
  source_url: string | null;
}

interface FinancialsResponse {
  company: Company;
  financials: FinancialRow[];
  fromCache: boolean;
  warning: string | null;
}

export function formatValue(value: number | null): string {
  if (value === null) return "—";
  const abs = Math.abs(value);
  const formatted = new Intl.NumberFormat("en-US", {
    maximumFractionDigits: abs < 100 ? 2 : 0,
  }).format(abs);
  return value < 0 ? `(${formatted})` : formatted;
}

async function fetchFinancials(
  ticker: string,
  period: string,
  fyear: number
): Promise<FinancialsResponse> {
  const params = new URLSearchParams({ ticker, period, fyear: String(fyear) });
  const res = await fetch(`/api/financials?${params}`);
  const body = await res.json();
  if (!res.ok) throw new Error(body.error ?? `Request failed (${res.status})`);
  return body;
}

function FinancialsExplorerInner() {
  // Deep-link support: /dashboard?ticker=GOOG auto-loads that company
  // (used by Scout when it routes single-company lookups here).
  const initialTicker =
    useSearchParams().get("ticker")?.trim().toUpperCase() ?? "";

  const [tickerInput, setTickerInput] = useState(initialTicker);
  const [query, setQuery] = useState<{
    ticker: string;
    period: string;
    fyear: number;
  } | null>(
    initialTicker
      ? { ticker: initialTicker, period: "FY", fyear: CURRENT_YEAR - 1 }
      : null
  );
  const [period, setPeriod] = useState<string>("FY");
  const [fyear, setFyear] = useState<number>(CURRENT_YEAR - 1);

  const { data, isFetching, error } = useQuery({
    queryKey: ["financials", query],
    queryFn: () => fetchFinancials(query!.ticker, query!.period, query!.fyear),
    enabled: query !== null,
  });

  function onSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!tickerInput.trim()) return;
    setQuery({ ticker: tickerInput.trim().toUpperCase(), period, fyear });
  }

  return (
    <div className="space-y-6">
      <form onSubmit={onSubmit} className="flex flex-wrap items-end gap-3">
        <div>
          <label className="mb-1 block text-sm font-medium text-slate-700">
            Ticker
          </label>
          <input
            value={tickerInput}
            onChange={(e) => setTickerInput(e.target.value)}
            placeholder="e.g. AAPL"
            className="w-36 rounded-md border border-slate-300 px-3 py-2 text-sm uppercase focus:border-blue-500 focus:outline-none"
          />
        </div>
        <div>
          <label className="mb-1 block text-sm font-medium text-slate-700">
            Period
          </label>
          <select
            value={period}
            onChange={(e) => setPeriod(e.target.value)}
            className="rounded-md border border-slate-300 px-3 py-2 text-sm"
          >
            {PERIODS.map((p) => (
              <option key={p}>{p}</option>
            ))}
          </select>
        </div>
        <div>
          <label className="mb-1 block text-sm font-medium text-slate-700">
            Fiscal year
          </label>
          <select
            value={fyear}
            onChange={(e) => setFyear(Number(e.target.value))}
            className="rounded-md border border-slate-300 px-3 py-2 text-sm"
          >
            {YEARS.map((y) => (
              <option key={y}>{y}</option>
            ))}
          </select>
        </div>
        <button
          type="submit"
          disabled={isFetching}
          className="rounded-md bg-blue-600 px-4 py-2 text-sm font-medium text-white hover:bg-blue-700 disabled:opacity-50"
        >
          {isFetching ? "Loading…" : "Search"}
        </button>
      </form>

      {error instanceof Error && (
        <div className="rounded-md border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">
          {error.message}
        </div>
      )}

      {data && (
        <div className="space-y-4">
          <div>
            <h2 className="text-xl font-semibold">
              {data.company.name}{" "}
              <span className="text-slate-500">({data.company.ticker})</span>
            </h2>
            <p className="text-sm text-slate-600">
              {[data.company.sector, data.company.industry]
                .filter(Boolean)
                .join(" · ") || "Sector unknown"}
              {" · "}
              {data.fromCache ? "served from cache" : "freshly fetched from SimFin"}
            </p>
            {data.warning && (
              <p className="mt-1 text-sm text-amber-700">{data.warning}</p>
            )}
          </div>

          {data.financials.length === 0 ? (
            <p className="text-sm text-slate-600">
              No line items found for this period. Try a different fiscal year.
            </p>
          ) : (
            <div className="overflow-hidden rounded-lg border border-slate-200 bg-white">
              <table className="w-full text-sm">
                <thead className="bg-slate-100 text-left">
                  <tr>
                    <th className="px-4 py-2 font-medium">Line item</th>
                    <th className="px-4 py-2 text-right font-medium">Value</th>
                    <th className="px-4 py-2 font-medium">Source</th>
                  </tr>
                </thead>
                <tbody>
                  {data.financials.map((row) => (
                    <tr key={row.id} className="border-t border-slate-100">
                      <td className="px-4 py-2">{row.line_item}</td>
                      <td
                        className={`px-4 py-2 text-right tabular-nums ${
                          row.is_hardcoded ? "text-blue-700" : "text-slate-900"
                        }`}
                      >
                        {formatValue(row.value)}
                      </td>
                      <td className="px-4 py-2">
                        {row.source_url ? (
                          // SimFin sources are per statement/filing, not per
                          // value — label honestly so users know what opens.
                          <a
                            href={row.source_url}
                            target="_blank"
                            rel="noreferrer"
                            title={
                              row.source_url.includes("sec.gov")
                                ? "Opens the SEC filing this statement was sourced from (filing-level link, not the exact disclosure)"
                                : "SimFin did not provide a filing link — opens the SimFin company page"
                            }
                            className="text-blue-600 hover:underline"
                          >
                            {row.source_url.includes("sec.gov")
                              ? "filing ↗"
                              : "SimFin ↗"}
                          </a>
                        ) : (
                          "—"
                        )}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

export default function FinancialsExplorer() {
  // useSearchParams requires a Suspense boundary during prerender.
  return (
    <Suspense>
      <FinancialsExplorerInner />
    </Suspense>
  );
}
