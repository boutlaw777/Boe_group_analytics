"use client";

import { useState } from "react";
import { useQuery } from "@tanstack/react-query";

const CURRENT_YEAR = new Date().getFullYear();
const YEAR_CHOICES = Array.from({ length: 8 }, (_, i) => CURRENT_YEAR - 1 - i);
const PERIODS = ["FY", "Q1", "Q2", "Q3", "Q4"] as const;

const UNIT_OPTIONS = [
  { value: "millions", label: "$ millions" },
  { value: "billions", label: "$ billions" },
  { value: "raw", label: "Raw units" },
] as const;
type Units = (typeof UNIT_OPTIONS)[number]["value"];

interface TemplateRow {
  id: string;
  name: string;
}

async function fetchTemplates(): Promise<TemplateRow[]> {
  const res = await fetch("/api/templates");
  const body = await res.json();
  if (!res.ok) throw new Error(body.error ?? "Failed to load templates");
  return body.templates;
}

async function fetchLineItems(
  ticker: string,
  period: string,
  fyear: number
): Promise<string[]> {
  const params = new URLSearchParams({ ticker, period, fyear: String(fyear) });
  const res = await fetch(`/api/financials?${params}`);
  const body = await res.json();
  if (!res.ok) throw new Error(body.error ?? `Request failed (${res.status})`);
  return [
    ...new Set<string>(
      (body.financials as { line_item: string }[]).map((r) => r.line_item)
    ),
  ];
}

export default function DataSheetBuilder() {
  const [ticker, setTicker] = useState("");
  const [period, setPeriod] = useState<string>("FY");
  const [years, setYears] = useState<number[]>([CURRENT_YEAR - 1]);
  const [loadedFor, setLoadedFor] = useState<{
    ticker: string;
    period: string;
    year: number;
  } | null>(null);
  const [selectedItems, setSelectedItems] = useState<Set<string>>(new Set());
  const [templateId, setTemplateId] = useState<string>("");
  const [units, setUnits] = useState<Units>("millions");
  const [generating, setGenerating] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const templatesQuery = useQuery({
    queryKey: ["templates"],
    queryFn: fetchTemplates,
  });

  const lineItemsQuery = useQuery({
    queryKey: ["lineItems", loadedFor],
    queryFn: async () => {
      const items = await fetchLineItems(
        loadedFor!.ticker,
        loadedFor!.period,
        loadedFor!.year
      );
      setSelectedItems(new Set(items)); // default: everything selected
      return items;
    },
    enabled: loadedFor !== null,
  });

  function toggleYear(year: number) {
    setYears((prev) =>
      prev.includes(year)
        ? prev.filter((y) => y !== year)
        : [...prev, year].sort((a, b) => a - b)
    );
  }

  function toggleItem(item: string) {
    setSelectedItems((prev) => {
      const next = new Set(prev);
      if (next.has(item)) next.delete(item);
      else next.add(item);
      return next;
    });
  }

  function loadItems(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    if (!ticker.trim() || years.length === 0) {
      setError("Enter a ticker and select at least one year.");
      return;
    }
    setLoadedFor({
      ticker: ticker.trim().toUpperCase(),
      period,
      year: Math.max(...years),
    });
  }

  async function generateExcel() {
    setError(null);
    setGenerating(true);
    try {
      const res = await fetch("/api/excel", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          ticker: ticker.trim().toUpperCase(),
          period,
          years,
          lineItems: [...selectedItems],
          units,
          ...(templateId ? { templateId } : {}),
        }),
      });
      if (!res.ok) {
        const body = await res.json().catch(() => ({}));
        throw new Error(body.error ?? `Excel generation failed (${res.status})`);
      }
      const blob = await res.blob();
      const filename =
        res.headers
          .get("Content-Disposition")
          ?.match(/filename="(.+)"/)?.[1] ?? "datasheet.xlsx";
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = filename;
      a.click();
      URL.revokeObjectURL(url);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Excel generation failed");
    } finally {
      setGenerating(false);
    }
  }

  return (
    <div className="space-y-6">
      <form
        onSubmit={loadItems}
        className="space-y-4 rounded-lg border border-slate-200 bg-white p-5"
      >
        <div className="flex flex-wrap items-end gap-3">
          <div>
            <label className="mb-1 block text-sm font-medium text-slate-700">
              Ticker
            </label>
            <input
              value={ticker}
              onChange={(e) => setTicker(e.target.value)}
              placeholder="e.g. MSFT"
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
          <button
            type="submit"
            disabled={lineItemsQuery.isFetching}
            className="rounded-md bg-blue-600 px-4 py-2 text-sm font-medium text-white hover:bg-blue-700 disabled:opacity-50"
          >
            {lineItemsQuery.isFetching ? "Loading…" : "Load line items"}
          </button>
        </div>

        <div>
          <span className="mb-1 block text-sm font-medium text-slate-700">
            Fiscal years
          </span>
          <div className="flex flex-wrap gap-3">
            {YEAR_CHOICES.map((year) => (
              <label key={year} className="flex items-center gap-1.5 text-sm">
                <input
                  type="checkbox"
                  checked={years.includes(year)}
                  onChange={() => toggleYear(year)}
                />
                {year}
              </label>
            ))}
          </div>
        </div>
      </form>

      {error && (
        <div className="rounded-md border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">
          {error}
        </div>
      )}
      {lineItemsQuery.error instanceof Error && (
        <div className="rounded-md border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">
          {lineItemsQuery.error.message}
        </div>
      )}

      {lineItemsQuery.data && (
        <div className="space-y-4 rounded-lg border border-slate-200 bg-white p-5">
          <div className="flex items-center justify-between">
            <h2 className="font-semibold">
              Line items ({selectedItems.size}/{lineItemsQuery.data.length}{" "}
              selected)
            </h2>
            <div className="flex gap-2 text-sm">
              <button
                onClick={() => setSelectedItems(new Set(lineItemsQuery.data))}
                className="text-blue-600 hover:underline"
              >
                Select all
              </button>
              <button
                onClick={() => setSelectedItems(new Set())}
                className="text-blue-600 hover:underline"
              >
                Clear
              </button>
            </div>
          </div>

          <div className="grid max-h-80 grid-cols-2 gap-1 overflow-y-auto md:grid-cols-3">
            {lineItemsQuery.data.map((item) => (
              <label key={item} className="flex items-center gap-1.5 text-sm">
                <input
                  type="checkbox"
                  checked={selectedItems.has(item)}
                  onChange={() => toggleItem(item)}
                />
                <span className="truncate" title={item}>
                  {item}
                </span>
              </label>
            ))}
          </div>

          <div className="flex flex-wrap items-end gap-3 border-t border-slate-100 pt-4">
            <div>
              <label className="mb-1 block text-sm font-medium text-slate-700">
                Units
              </label>
              <select
                value={units}
                onChange={(e) => setUnits(e.target.value as Units)}
                className="rounded-md border border-slate-300 px-3 py-2 text-sm"
              >
                {UNIT_OPTIONS.map((u) => (
                  <option key={u.value} value={u.value}>
                    {u.label}
                  </option>
                ))}
              </select>
            </div>
            <div>
              <label className="mb-1 block text-sm font-medium text-slate-700">
                Template (optional)
              </label>
              <select
                value={templateId}
                onChange={(e) => setTemplateId(e.target.value)}
                className="min-w-48 rounded-md border border-slate-300 px-3 py-2 text-sm"
              >
                <option value="">None — default layout</option>
                {(templatesQuery.data ?? []).map((t) => (
                  <option key={t.id} value={t.id}>
                    {t.name}
                  </option>
                ))}
              </select>
            </div>
            <button
              onClick={generateExcel}
              disabled={generating || selectedItems.size === 0}
              className="rounded-md bg-emerald-600 px-4 py-2 text-sm font-medium text-white hover:bg-emerald-700 disabled:opacity-50"
            >
              {generating ? "Generating…" : "Generate Excel"}
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
