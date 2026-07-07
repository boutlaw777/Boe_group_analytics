"use client";

import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

const CURRENT_YEAR = new Date().getFullYear();

interface FormulaToken {
  type: "item" | "op" | "number";
  value: string;
}

interface CustomFormula {
  name: string;
  tokens: FormulaToken[];
}

interface TemplateRow {
  id: string;
  name: string;
  row_mapping_json: string[];
  custom_formulas_json: CustomFormula[];
  created_at: string;
}

const OPERATORS = ["+", "-", "*", "/", "(", ")"];

async function fetchTemplates(): Promise<TemplateRow[]> {
  const res = await fetch("/api/templates");
  const body = await res.json();
  if (!res.ok) throw new Error(body.error ?? "Failed to load templates");
  return body.templates;
}

async function fetchLineItems(ticker: string): Promise<string[]> {
  const params = new URLSearchParams({
    ticker,
    period: "FY",
    fyear: String(CURRENT_YEAR - 1),
  });
  const res = await fetch(`/api/financials?${params}`);
  const body = await res.json();
  if (!res.ok) throw new Error(body.error ?? `Request failed (${res.status})`);
  return [
    ...new Set<string>(
      (body.financials as { line_item: string }[]).map((r) => r.line_item)
    ),
  ];
}

export default function TemplateBuilder() {
  const queryClient = useQueryClient();

  // -- template being built
  const [name, setName] = useState("");
  const [ticker, setTicker] = useState("");
  const [rowOrder, setRowOrder] = useState<string[]>([]);
  const [formulas, setFormulas] = useState<CustomFormula[]>([]);
  const [dragIndex, setDragIndex] = useState<number | null>(null);
  const [error, setError] = useState<string | null>(null);

  // -- formula under construction
  const [formulaName, setFormulaName] = useState("");
  const [tokens, setTokens] = useState<FormulaToken[]>([]);
  const [numberInput, setNumberInput] = useState("");

  const templatesQuery = useQuery({ queryKey: ["templates"], queryFn: fetchTemplates });

  const loadItems = useMutation({
    mutationFn: () => fetchLineItems(ticker.trim().toUpperCase()),
    onSuccess: (items) => {
      setRowOrder(items);
      setError(null);
    },
    onError: (err) => setError(err instanceof Error ? err.message : "Load failed"),
  });

  const saveTemplate = useMutation({
    mutationFn: async () => {
      const res = await fetch("/api/templates", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          name: name.trim(),
          rowMapping: rowOrder,
          customFormulas: formulas,
        }),
      });
      const body = await res.json();
      if (!res.ok) throw new Error(body.error ?? "Save failed");
      return body.template;
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["templates"] });
      setName("");
      setRowOrder([]);
      setFormulas([]);
      setError(null);
    },
    onError: (err) => setError(err instanceof Error ? err.message : "Save failed"),
  });

  const deleteTemplate = useMutation({
    mutationFn: async (id: string) => {
      const res = await fetch(`/api/templates/${id}`, { method: "DELETE" });
      if (!res.ok) {
        const body = await res.json().catch(() => ({}));
        throw new Error(body.error ?? "Delete failed");
      }
    },
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["templates"] }),
  });

  // ---- drag & drop reordering
  function onDrop(targetIndex: number) {
    if (dragIndex === null || dragIndex === targetIndex) return;
    setRowOrder((prev) => {
      const next = [...prev];
      const [moved] = next.splice(dragIndex, 1);
      next.splice(targetIndex, 0, moved);
      return next;
    });
    setDragIndex(null);
  }

  function moveRow(index: number, delta: number) {
    const target = index + delta;
    if (target < 0 || target >= rowOrder.length) return;
    setRowOrder((prev) => {
      const next = [...prev];
      [next[index], next[target]] = [next[target], next[index]];
      return next;
    });
  }

  // ---- formula builder
  function addFormula() {
    if (!formulaName.trim() || tokens.length === 0) return;
    setFormulas((prev) => [...prev, { name: formulaName.trim(), tokens }]);
    setFormulaName("");
    setTokens([]);
  }

  function formulaPreview(f: { tokens: FormulaToken[] }): string {
    return f.tokens
      .map((t) => (t.type === "item" ? `[${t.value}]` : t.value))
      .join(" ");
  }

  return (
    <div className="grid gap-6 lg:grid-cols-2">
      {/* ---------------- builder ---------------- */}
      <div className="space-y-5 rounded-lg border border-slate-200 bg-white p-5">
        <h2 className="font-semibold">New template</h2>

        <div className="flex flex-wrap items-end gap-3">
          <div>
            <label className="mb-1 block text-sm font-medium text-slate-700">
              Template name
            </label>
            <input
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder="e.g. My SaaS Model"
              className="w-52 rounded-md border border-slate-300 px-3 py-2 text-sm"
            />
          </div>
          <div>
            <label className="mb-1 block text-sm font-medium text-slate-700">
              Load line items from ticker
            </label>
            <input
              value={ticker}
              onChange={(e) => setTicker(e.target.value)}
              placeholder="e.g. AAPL"
              className="w-32 rounded-md border border-slate-300 px-3 py-2 text-sm uppercase"
            />
          </div>
          <button
            onClick={() => ticker.trim() && loadItems.mutate()}
            disabled={loadItems.isPending}
            className="rounded-md bg-blue-600 px-4 py-2 text-sm font-medium text-white hover:bg-blue-700 disabled:opacity-50"
          >
            {loadItems.isPending ? "Loading…" : "Load"}
          </button>
        </div>

        {error && (
          <div className="rounded-md border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">
            {error}
          </div>
        )}

        {rowOrder.length > 0 && (
          <>
            <div>
              <h3 className="mb-2 text-sm font-medium text-slate-700">
                Row order — drag to reorder
              </h3>
              <ul className="max-h-72 space-y-1 overflow-y-auto">
                {rowOrder.map((item, i) => (
                  <li
                    key={item}
                    draggable
                    onDragStart={() => setDragIndex(i)}
                    onDragOver={(e) => e.preventDefault()}
                    onDrop={() => onDrop(i)}
                    className="flex cursor-grab items-center justify-between rounded border border-slate-200 bg-slate-50 px-3 py-1.5 text-sm active:cursor-grabbing"
                  >
                    <span className="truncate">
                      <span className="mr-2 text-slate-400">⠿</span>
                      {item}
                    </span>
                    <span className="flex gap-1">
                      <button
                        onClick={() => moveRow(i, -1)}
                        className="px-1 text-slate-500 hover:text-slate-900"
                        title="Move up"
                      >
                        ↑
                      </button>
                      <button
                        onClick={() => moveRow(i, 1)}
                        className="px-1 text-slate-500 hover:text-slate-900"
                        title="Move down"
                      >
                        ↓
                      </button>
                    </span>
                  </li>
                ))}
              </ul>
            </div>

            <div className="space-y-3 border-t border-slate-100 pt-4">
              <h3 className="text-sm font-medium text-slate-700">
                Custom formulas
              </h3>

              {formulas.length > 0 && (
                <ul className="space-y-1 text-sm">
                  {formulas.map((f, i) => (
                    <li
                      key={i}
                      className="flex items-center justify-between rounded bg-emerald-50 px-3 py-1.5"
                    >
                      <span>
                        <strong>{f.name}</strong> = {formulaPreview(f)}
                      </span>
                      <button
                        onClick={() =>
                          setFormulas((prev) => prev.filter((_, j) => j !== i))
                        }
                        className="text-red-600 hover:underline"
                      >
                        remove
                      </button>
                    </li>
                  ))}
                </ul>
              )}

              <input
                value={formulaName}
                onChange={(e) => setFormulaName(e.target.value)}
                placeholder="Formula name, e.g. Adjusted EBITDA"
                className="w-full rounded-md border border-slate-300 px-3 py-2 text-sm"
              />

              <div className="min-h-10 rounded-md border border-dashed border-slate-300 px-3 py-2 text-sm">
                {tokens.length === 0 ? (
                  <span className="text-slate-400">
                    Build the expression below…
                  </span>
                ) : (
                  formulaPreview({ tokens })
                )}
              </div>

              <div className="flex flex-wrap items-center gap-2">
                <select
                  onChange={(e) => {
                    const value = e.target.value;
                    if (!value) return;
                    setTokens((prev) => [...prev, { type: "item", value }]);
                    e.target.value = "";
                  }}
                  className="rounded-md border border-slate-300 px-2 py-1.5 text-sm"
                  defaultValue=""
                >
                  <option value="" disabled>
                    + line item
                  </option>
                  {rowOrder.map((item) => (
                    <option key={item}>{item}</option>
                  ))}
                </select>

                {OPERATORS.map((op) => (
                  <button
                    key={op}
                    onClick={() =>
                      setTokens((prev) => [...prev, { type: "op", value: op }])
                    }
                    className="rounded border border-slate-300 px-2.5 py-1 text-sm hover:bg-slate-100"
                  >
                    {op}
                  </button>
                ))}

                <input
                  value={numberInput}
                  onChange={(e) => setNumberInput(e.target.value)}
                  placeholder="123"
                  className="w-20 rounded-md border border-slate-300 px-2 py-1.5 text-sm"
                />
                <button
                  onClick={() => {
                    const n = Number(numberInput);
                    if (!Number.isFinite(n)) return;
                    setTokens((prev) => [
                      ...prev,
                      { type: "number", value: String(n) },
                    ]);
                    setNumberInput("");
                  }}
                  className="rounded border border-slate-300 px-2.5 py-1 text-sm hover:bg-slate-100"
                >
                  + number
                </button>

                <button
                  onClick={() => setTokens((prev) => prev.slice(0, -1))}
                  className="rounded border border-slate-300 px-2.5 py-1 text-sm text-red-600 hover:bg-red-50"
                >
                  ⌫ undo
                </button>
              </div>

              <button
                onClick={addFormula}
                disabled={!formulaName.trim() || tokens.length === 0}
                className="rounded-md bg-slate-800 px-4 py-2 text-sm font-medium text-white hover:bg-slate-900 disabled:opacity-50"
              >
                Add formula
              </button>
            </div>

            <button
              onClick={() => saveTemplate.mutate()}
              disabled={!name.trim() || saveTemplate.isPending}
              className="w-full rounded-md bg-emerald-600 px-4 py-2.5 text-sm font-medium text-white hover:bg-emerald-700 disabled:opacity-50"
            >
              {saveTemplate.isPending ? "Saving…" : "Save template"}
            </button>
          </>
        )}
      </div>

      {/* ---------------- saved templates ---------------- */}
      <div className="space-y-4 rounded-lg border border-slate-200 bg-white p-5">
        <h2 className="font-semibold">Saved templates</h2>
        {templatesQuery.isLoading && (
          <p className="text-sm text-slate-500">Loading…</p>
        )}
        {templatesQuery.data?.length === 0 && (
          <p className="text-sm text-slate-500">
            No templates yet. Build one on the left — then select it when
            generating a Data Sheet.
          </p>
        )}
        <ul className="space-y-3">
          {(templatesQuery.data ?? []).map((t) => (
            <li key={t.id} className="rounded-md border border-slate-200 p-3">
              <div className="flex items-center justify-between">
                <strong className="text-sm">{t.name}</strong>
                <button
                  onClick={() => deleteTemplate.mutate(t.id)}
                  className="text-sm text-red-600 hover:underline"
                >
                  delete
                </button>
              </div>
              <p className="mt-1 text-xs text-slate-500">
                {t.row_mapping_json.length} ordered rows ·{" "}
                {t.custom_formulas_json.length} custom formula
                {t.custom_formulas_json.length === 1 ? "" : "s"}
              </p>
              {t.custom_formulas_json.length > 0 && (
                <ul className="mt-2 space-y-0.5 text-xs text-slate-600">
                  {t.custom_formulas_json.map((f, i) => (
                    <li key={i}>
                      {f.name} = {formulaPreview(f)}
                    </li>
                  ))}
                </ul>
              )}
            </li>
          ))}
        </ul>
      </div>
    </div>
  );
}
