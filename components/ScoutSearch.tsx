"use client";

import { useState } from "react";
import Link from "next/link";
import { useMutation } from "@tanstack/react-query";

interface ScreenFilter {
  sector: string | null;
  metric: string;
  isGrowth: boolean;
  operator: string;
  value: number;
  fiscalYear: number | null;
}

interface PartialFilter {
  sector: string | null;
  metric: string;
  isGrowth: boolean;
  fiscalYear: number | null;
}

interface ScreenResult {
  companyId: string;
  ticker: string;
  name: string;
  sector: string | null;
  industry: string | null;
  metricValue: number;
  fiscalYear: number;
}

type ScoutResponse =
  | {
      kind: "results";
      filter: ScreenFilter;
      results: ScreenResult[];
      note: string | null;
    }
  | {
      kind: "lookup";
      ticker: string;
      metric: string;
      fiscalYear: number | null;
    }
  | { kind: "needs_threshold"; filter: PartialFilter };

const EXAMPLES = [
  "software companies with revenue growth over 20%",
  "companies with net income above $1B",
  "retail companies with revenue over $50B in 2023",
];

const OPERATORS = [">", ">=", "<", "<=", "="] as const;

function formatMetric(value: number, isGrowth: boolean): string {
  if (isGrowth) return `${value.toFixed(1)}%`;
  const abs = Math.abs(value);
  const formatted =
    abs >= 1e9
      ? `${(abs / 1e9).toFixed(2)}B`
      : abs >= 1e6
        ? `${(abs / 1e6).toFixed(1)}M`
        : new Intl.NumberFormat("en-US").format(abs);
  return value < 0 ? `(${formatted})` : formatted;
}

/** Parse "1.5B", "$500M", "20", "1,000,000" into a number, else null. */
function parseThreshold(input: string): number | null {
  const cleaned = input.trim().replace(/[$,\s]/g, "");
  const match = cleaned.match(/^(-?\d+(?:\.\d+)?)([kmbt])?$/i);
  if (!match) return null;
  const base = Number(match[1]);
  const mult =
    { k: 1e3, m: 1e6, b: 1e9, t: 1e12 }[match[2]?.toLowerCase() ?? ""] ?? 1;
  return base * mult;
}

export default function ScoutSearch() {
  const [query, setQuery] = useState("");
  const [added, setAdded] = useState<Set<string>>(new Set());
  const [thresholdOp, setThresholdOp] =
    useState<(typeof OPERATORS)[number]>(">");
  const [thresholdInput, setThresholdInput] = useState("");
  const [thresholdError, setThresholdError] = useState<string | null>(null);

  const search = useMutation({
    mutationFn: async (
      body: { query: string } | { filter: ScreenFilter }
    ): Promise<ScoutResponse> => {
      const res = await fetch("/api/scout", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
      const resBody = await res.json();
      if (!res.ok) throw new Error(resBody.error ?? "Search failed");
      return resBody;
    },
    onSuccess: () => {
      setAdded(new Set());
      setThresholdInput("");
      setThresholdError(null);
    },
  });

  const addToWatchlist = useMutation({
    mutationFn: async (companyId: string) => {
      const res = await fetch("/api/watchlist", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ companyId }),
      });
      if (!res.ok) {
        const body = await res.json().catch(() => ({}));
        throw new Error(body.error ?? "Failed to add to watchlist");
      }
      return companyId;
    },
    onSuccess: (companyId) =>
      setAdded((prev) => new Set(prev).add(companyId)),
  });

  function runWithThreshold(partial: PartialFilter) {
    const value = parseThreshold(thresholdInput);
    if (value === null) {
      setThresholdError(
        partial.isGrowth
          ? "Enter a percentage, e.g. 20"
          : "Enter an amount, e.g. 1B, 500M or 1000000000"
      );
      return;
    }
    setThresholdError(null);
    search.mutate({
      filter: { ...partial, operator: thresholdOp, value },
    });
  }

  function exportCsv() {
    const data = search.data;
    if (!data || data.kind !== "results" || data.results.length === 0) return;
    const isGrowth = data.filter.isGrowth;
    const metricLabel = isGrowth
      ? `${data.filter.metric} Growth %`
      : data.filter.metric;
    const header = ["Ticker", "Name", "Sector", "Industry", metricLabel, "Fiscal Year"];
    const lines = [
      header.join(","),
      ...data.results.map((r) =>
        [
          r.ticker,
          `"${r.name.replace(/"/g, '""')}"`,
          `"${(r.sector ?? "").replace(/"/g, '""')}"`,
          `"${(r.industry ?? "").replace(/"/g, '""')}"`,
          isGrowth ? r.metricValue.toFixed(2) : r.metricValue,
          r.fiscalYear,
        ].join(",")
      ),
    ];
    const blob = new Blob([lines.join("\n")], { type: "text/csv" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = "scout_results.csv";
    a.click();
    URL.revokeObjectURL(url);
  }

  const data = search.data;

  return (
    <div className="space-y-6">
      <form
        onSubmit={(e) => {
          e.preventDefault();
          if (query.trim().length >= 3) search.mutate({ query: query.trim() });
        }}
        className="flex gap-2"
      >
        <input
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder='e.g. "software companies with revenue growth over 20%"'
          className="flex-1 rounded-md border border-slate-300 px-4 py-2.5 text-sm focus:border-blue-500 focus:outline-none"
        />
        <button
          type="submit"
          disabled={search.isPending}
          className="rounded-md bg-blue-600 px-5 py-2.5 text-sm font-medium text-white hover:bg-blue-700 disabled:opacity-50"
        >
          {search.isPending ? "Searching…" : "Search"}
        </button>
      </form>

      <div className="flex flex-wrap gap-2 text-sm">
        {EXAMPLES.map((ex) => (
          <button
            key={ex}
            onClick={() => {
              setQuery(ex);
              search.mutate({ query: ex });
            }}
            className="rounded-full border border-slate-300 px-3 py-1 text-slate-600 hover:border-blue-400 hover:text-blue-700"
          >
            {ex}
          </button>
        ))}
      </div>

      {search.error instanceof Error && (
        <div className="rounded-md border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">
          {search.error.message}
        </div>
      )}

      {data?.kind === "lookup" && (
        <div className="space-y-2 rounded-md border border-blue-200 bg-blue-50 px-4 py-3 text-sm text-blue-900">
          <p>
            This looks like a question about a single company (
            <span className="font-semibold">{data.ticker}</span>
            {data.metric ? ` — ${data.metric}` : ""}), not a screen. Company
            fundamentals live in the Overview view.
          </p>
          <Link
            href={`/dashboard?ticker=${encodeURIComponent(data.ticker)}`}
            className="inline-block rounded-md bg-blue-600 px-3 py-1.5 font-medium text-white hover:bg-blue-700"
          >
            Open {data.ticker} in Overview →
          </Link>
        </div>
      )}

      {data?.kind === "needs_threshold" && (
        <div className="space-y-3 rounded-md border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-900">
          <p>
            Your query names{" "}
            <span className="font-semibold">
              {data.filter.metric}
              {data.filter.isGrowth ? " growth" : ""}
            </span>{" "}
            but no threshold. Set one to run the screen — Scout won&apos;t
            assume a cutoff for you.
          </p>
          <div className="flex flex-wrap items-center gap-2">
            <select
              value={thresholdOp}
              onChange={(e) =>
                setThresholdOp(e.target.value as (typeof OPERATORS)[number])
              }
              className="rounded-md border border-amber-300 bg-white px-2 py-1.5"
            >
              {OPERATORS.map((op) => (
                <option key={op}>{op}</option>
              ))}
            </select>
            <input
              value={thresholdInput}
              onChange={(e) => setThresholdInput(e.target.value)}
              placeholder={data.filter.isGrowth ? "e.g. 20 (%)" : "e.g. 1B or 500M"}
              className="w-40 rounded-md border border-amber-300 bg-white px-3 py-1.5"
            />
            <button
              onClick={() => runWithThreshold(data.filter)}
              disabled={search.isPending}
              className="rounded-md bg-amber-600 px-3 py-1.5 font-medium text-white hover:bg-amber-700 disabled:opacity-50"
            >
              Run screen
            </button>
          </div>
          {thresholdError && <p className="text-red-700">{thresholdError}</p>}
        </div>
      )}

      {data?.kind === "results" && (
        <div className="space-y-4">
          <div className="flex flex-wrap items-center gap-2 text-sm">
            <span className="text-slate-500">Interpreted as:</span>
            {data.filter.sector && (
              <span className="rounded-full bg-blue-100 px-3 py-0.5 text-blue-800">
                sector ≈ {data.filter.sector}
              </span>
            )}
            <span className="rounded-full bg-blue-100 px-3 py-0.5 text-blue-800">
              {data.filter.metric}
              {data.filter.isGrowth ? " growth" : ""} {data.filter.operator}{" "}
              {formatMetric(data.filter.value, data.filter.isGrowth)}
            </span>
            {data.filter.fiscalYear && (
              <span className="rounded-full bg-blue-100 px-3 py-0.5 text-blue-800">
                FY{data.filter.fiscalYear}
              </span>
            )}
          </div>

          {data.note && (
            <div className="rounded-md border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-800">
              {data.note}
            </div>
          )}

          {data.results.length > 0 && (
            <div className="space-y-3">
              <div className="flex items-center justify-between">
                <h2 className="font-semibold">
                  {data.results.length} match
                  {data.results.length === 1 ? "" : "es"}
                </h2>
                <button
                  onClick={exportCsv}
                  className="rounded-md border border-slate-300 px-3 py-1.5 text-sm font-medium hover:bg-slate-100"
                >
                  Bulk Export (CSV)
                </button>
              </div>

              <div className="overflow-hidden rounded-lg border border-slate-200 bg-white">
                <table className="w-full text-sm">
                  <thead className="bg-slate-100 text-left">
                    <tr>
                      <th className="px-4 py-2 font-medium">Ticker</th>
                      <th className="px-4 py-2 font-medium">Company</th>
                      <th className="px-4 py-2 font-medium">Sector</th>
                      <th className="px-4 py-2 text-right font-medium">
                        {data.filter.metric}
                        {data.filter.isGrowth ? " growth" : ""}
                      </th>
                      <th className="px-4 py-2 font-medium">FY</th>
                      <th className="px-4 py-2 font-medium">Actions</th>
                    </tr>
                  </thead>
                  <tbody>
                    {data.results.map((r) => (
                      <tr key={r.companyId} className="border-t border-slate-100">
                        <td className="px-4 py-2 font-medium">{r.ticker}</td>
                        <td className="px-4 py-2">{r.name}</td>
                        <td className="px-4 py-2 text-slate-600">
                          {r.sector ?? "—"}
                        </td>
                        <td className="px-4 py-2 text-right tabular-nums">
                          {formatMetric(r.metricValue, data.filter.isGrowth)}
                        </td>
                        <td className="px-4 py-2">{r.fiscalYear}</td>
                        <td className="px-4 py-2">
                          {added.has(r.companyId) ? (
                            <span className="text-emerald-600">✓ watching</span>
                          ) : (
                            <button
                              onClick={() => addToWatchlist.mutate(r.companyId)}
                              className="text-blue-600 hover:underline"
                            >
                              Add to Watchlist
                            </button>
                          )}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
