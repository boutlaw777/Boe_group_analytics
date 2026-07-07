"use client";

import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

interface ApiKeyRow {
  id: string;
  key: string;
  tier: string;
  request_count: number;
  revoked: boolean;
  created_at: string;
}

async function fetchKeys(): Promise<ApiKeyRow[]> {
  const res = await fetch("/api/keys");
  const body = await res.json();
  if (!res.ok) throw new Error(body.error ?? "Failed to load keys");
  return body.keys;
}

export default function ApiKeyManager() {
  const queryClient = useQueryClient();
  const [tier, setTier] = useState<"free" | "pro">("free");
  const [copied, setCopied] = useState<string | null>(null);

  const keysQuery = useQuery({ queryKey: ["apiKeys"], queryFn: fetchKeys });

  const createKey = useMutation({
    mutationFn: async () => {
      const res = await fetch("/api/keys", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ tier }),
      });
      const body = await res.json();
      if (!res.ok) throw new Error(body.error ?? "Failed to create key");
      return body.apiKey as ApiKeyRow;
    },
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["apiKeys"] }),
  });

  const revokeKey = useMutation({
    mutationFn: async (id: string) => {
      const res = await fetch(`/api/keys?id=${id}`, { method: "DELETE" });
      if (!res.ok) {
        const body = await res.json().catch(() => ({}));
        throw new Error(body.error ?? "Failed to revoke key");
      }
    },
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["apiKeys"] }),
  });

  async function copy(key: string) {
    await navigator.clipboard.writeText(key);
    setCopied(key);
    setTimeout(() => setCopied(null), 1500);
  }

  return (
    <div className="space-y-6">
      <div className="flex items-end gap-3 rounded-lg border border-slate-200 bg-white p-5">
        <div>
          <label className="mb-1 block text-sm font-medium text-slate-700">
            Tier
          </label>
          <select
            value={tier}
            onChange={(e) => setTier(e.target.value as "free" | "pro")}
            className="rounded-md border border-slate-300 px-3 py-2 text-sm"
          >
            <option value="free">free — 10 req/min</option>
            <option value="pro">pro — 60 req/min</option>
          </select>
        </div>
        <button
          onClick={() => createKey.mutate()}
          disabled={createKey.isPending}
          className="rounded-md bg-blue-600 px-4 py-2 text-sm font-medium text-white hover:bg-blue-700 disabled:opacity-50"
        >
          {createKey.isPending ? "Generating…" : "Generate API key"}
        </button>
      </div>

      {(createKey.error ?? revokeKey.error) instanceof Error && (
        <div className="rounded-md border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">
          {((createKey.error ?? revokeKey.error) as Error).message}
        </div>
      )}

      <div className="overflow-hidden rounded-lg border border-slate-200 bg-white">
        <table className="w-full text-sm">
          <thead className="bg-slate-100 text-left">
            <tr>
              <th className="px-4 py-2 font-medium">Key</th>
              <th className="px-4 py-2 font-medium">Tier</th>
              <th className="px-4 py-2 text-right font-medium">Requests</th>
              <th className="px-4 py-2 font-medium">Status</th>
              <th className="px-4 py-2 font-medium">Actions</th>
            </tr>
          </thead>
          <tbody>
            {keysQuery.data?.length === 0 && (
              <tr>
                <td colSpan={5} className="px-4 py-6 text-center text-slate-500">
                  No API keys yet — generate one above.
                </td>
              </tr>
            )}
            {(keysQuery.data ?? []).map((k) => (
              <tr key={k.id} className="border-t border-slate-100">
                <td className="px-4 py-2 font-mono text-xs">
                  {k.key.slice(0, 12)}…{k.key.slice(-4)}
                  <button
                    onClick={() => copy(k.key)}
                    className="ml-2 text-blue-600 hover:underline"
                  >
                    {copied === k.key ? "copied!" : "copy"}
                  </button>
                </td>
                <td className="px-4 py-2">{k.tier}</td>
                <td className="px-4 py-2 text-right tabular-nums">
                  {k.request_count}
                </td>
                <td className="px-4 py-2">
                  {k.revoked ? (
                    <span className="text-red-600">revoked</span>
                  ) : (
                    <span className="text-emerald-600">active</span>
                  )}
                </td>
                <td className="px-4 py-2">
                  {!k.revoked && (
                    <button
                      onClick={() => revokeKey.mutate(k.id)}
                      className="text-red-600 hover:underline"
                    >
                      Revoke
                    </button>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <div className="rounded-lg border border-slate-200 bg-white p-5 text-sm">
        <h2 className="mb-2 font-semibold">Endpoints</h2>
        <p className="mb-3 text-slate-600">
          Send your key as <code className="rounded bg-slate-100 px-1">Authorization: Bearer &lt;api_key&gt;</code>
        </p>
        <ul className="space-y-1 font-mono text-xs text-slate-700">
          <li>GET /api/v1/companies</li>
          <li>GET /api/v1/financials?ticker=AAPL&amp;year=2023&amp;quarter=Q4</li>
          <li>GET /api/v1/industry_metrics?sector=Technology</li>
          <li>GET /api/v1/source_links?ticker=AAPL</li>
        </ul>
      </div>
    </div>
  );
}
