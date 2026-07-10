"use client";
import { useCallback, useEffect, useState } from "react";

const TOKEN_KEY = "boe_dev_token";

interface Key {
  id: number;
  name: string;
  prefix: string;
  tier: string;
  active: boolean;
  requests: number;
  created: string;
}
interface UsagePoint {
  date: string;
  requests: number;
}

/** Daily requests, single series: thin bars, one hue, hover tooltip, no legend. */
function UsageChart({ points }: { points: UsagePoint[] }) {
  const [hover, setHover] = useState<number | null>(null);
  const W = 640, H = 170, padL = 36, padB = 22, padT = 26;
  const plotW = W - padL - 8, plotH = H - padT - padB;
  const max = Math.max(1, ...points.map((p) => p.requests));
  const step = plotW / points.length;
  const barW = Math.max(3, step - 2); // 2px surface gap between bars
  const y = (v: number) => padT + plotH - (v / max) * plotH;
  const fmt = (iso: string) =>
    new Date(iso + "T00:00:00").toLocaleDateString("en-US", { month: "short", day: "numeric" });
  const total = points.reduce((s, p) => s + p.requests, 0);

  if (total === 0) {
    return (
      <p className="muted" style={{ padding: "24px 0" }}>
        No requests yet — traffic on your keys will chart here within a day.
      </p>
    );
  }
  return (
    <svg viewBox={`0 0 ${W} ${H}`} style={{ width: "100%", height: "auto", display: "block" }}
         role="img" aria-label={`Daily API requests, last ${points.length} days`}>
      {/* recessive grid: 3 lines */}
      {[0.5, 1].map((f) => (
        <line key={f} x1={padL} x2={W - 8} y1={y(max * f)} y2={y(max * f)}
              stroke="var(--border)" strokeWidth="1" />
      ))}
      <line x1={padL} x2={W - 8} y1={y(0)} y2={y(0)} stroke="var(--border)" strokeWidth="1" />
      {/* y max label */}
      <text x={padL - 6} y={y(max) + 4} textAnchor="end" fontSize="11" fill="var(--muted)">
        {max.toLocaleString()}
      </text>
      <text x={padL - 6} y={y(0) + 4} textAnchor="end" fontSize="11" fill="var(--muted)">0</text>
      {/* bars + oversized hover targets */}
      {points.map((p, i) => {
        const x = padL + i * step + 1;
        const h = Math.max(p.requests > 0 ? 2 : 0, (p.requests / max) * plotH);
        return (
          <g key={p.date}>
            {h > 0 && (
              <path
                d={`M${x},${y(0)} v${-Math.max(0, h - 2)} q0,-2 2,-2 h${barW - 4} q2,0 2,2 v${Math.max(0, h - 2)} z`}
                fill={hover === i ? "var(--navy)" : "var(--accent)"}
              />
            )}
            <rect x={padL + i * step} y={padT} width={step} height={plotH}
                  fill="transparent"
                  onMouseEnter={() => setHover(i)} onMouseLeave={() => setHover(null)} />
          </g>
        );
      })}
      {/* x labels: first and last day only */}
      <text x={padL} y={H - 6} fontSize="11" fill="var(--muted)">{fmt(points[0].date)}</text>
      <text x={W - 8} y={H - 6} textAnchor="end" fontSize="11" fill="var(--muted)">
        {fmt(points[points.length - 1].date)}
      </text>
      {/* hover tooltip */}
      {hover !== null && (
        <text x={W - 8} y={16} textAnchor="end" fontSize="12" fill="var(--text)">
          {fmt(points[hover].date)} — {points[hover].requests.toLocaleString()} request
          {points[hover].requests === 1 ? "" : "s"}
        </text>
      )}
    </svg>
  );
}

export function PortalClient({ apiBase }: { apiBase: string }) {
  const [token, setToken] = useState<string | null>(null);
  const [ready, setReady] = useState(false);
  const [mode, setMode] = useState<"login" | "signup">("signup");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  const [me, setMe] = useState<{ email: string } | null>(null);
  const [keys, setKeys] = useState<Key[]>([]);
  const [usage, setUsage] = useState<UsagePoint[]>([]);
  const [newKeyName, setNewKeyName] = useState("");
  const [freshKey, setFreshKey] = useState<{ name: string; api_key: string } | null>(null);
  const [copied, setCopied] = useState(false);

  useEffect(() => {
    setToken(localStorage.getItem(TOKEN_KEY));
    setReady(true);
  }, []);

  const authed = useCallback(
    async (path: string, init?: RequestInit) => {
      const t = localStorage.getItem(TOKEN_KEY);
      const res = await fetch(`${apiBase}${path}`, {
        ...init,
        headers: { ...(init?.headers ?? {}), Authorization: `Bearer ${t}`,
                   "Content-Type": "application/json" },
      });
      if (res.status === 401) {
        localStorage.removeItem(TOKEN_KEY);
        setToken(null);
        throw new Error("Session expired — log in again");
      }
      if (!res.ok) throw new Error((await res.json()).detail ?? `Error ${res.status}`);
      return res.json();
    },
    [apiBase],
  );

  const refresh = useCallback(async () => {
    const [meData, keyData, usageData] = await Promise.all([
      authed("/me"), authed("/me/keys"), authed("/me/usage?days=30"),
    ]);
    setMe(meData);
    setKeys(keyData);
    setUsage(usageData);
  }, [authed]);

  useEffect(() => {
    if (token) refresh().catch((e) => setError(e.message));
  }, [token, refresh]);

  async function submitAuth(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError("");
    try {
      const res = await fetch(`${apiBase}/auth/${mode}`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ email, password }),
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail ?? `Error ${res.status}`);
      localStorage.setItem(TOKEN_KEY, data.token);
      setToken(data.token);
      setPassword("");
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  }

  async function createKey() {
    setError("");
    try {
      const created = await authed("/me/keys", {
        method: "POST",
        body: JSON.stringify({ name: newKeyName || "default" }),
      });
      setFreshKey({ name: created.name, api_key: created.api_key });
      setCopied(false);
      setNewKeyName("");
      await refresh();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  }

  async function revokeKey(id: number) {
    setError("");
    try {
      await authed(`/me/keys/${id}`, { method: "DELETE" });
      await refresh();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  }

  function logout() {
    localStorage.removeItem(TOKEN_KEY);
    setToken(null);
    setMe(null);
    setKeys([]);
    setUsage([]);
    setFreshKey(null);
  }

  if (!ready) return null;

  if (!token) {
    return (
      <div className="card" style={{ maxWidth: 420, margin: "0 auto", padding: 28 }}>
        <div style={{ display: "flex", gap: 8, marginBottom: 18 }}>
          {(["signup", "login"] as const).map((m) => (
            <button key={m} className={mode === m ? "btn" : "btn secondary"}
                    style={{ flex: 1 }} onClick={() => { setMode(m); setError(""); }}>
              {m === "signup" ? "Create account" : "Log in"}
            </button>
          ))}
        </div>
        <form onSubmit={submitAuth}>
          <input type="email" required placeholder="you@company.com" value={email}
                 onChange={(e) => setEmail(e.target.value)}
                 style={{ width: "100%", padding: 10, marginBottom: 10,
                          border: "1px solid var(--border)", borderRadius: 6 }} />
          <input type="password" required minLength={8}
                 placeholder={mode === "signup" ? "Password (8+ characters)" : "Password"}
                 value={password} onChange={(e) => setPassword(e.target.value)}
                 style={{ width: "100%", padding: 10, marginBottom: 14,
                          border: "1px solid var(--border)", borderRadius: 6 }} />
          <button className="btn" style={{ width: "100%" }} disabled={busy}>
            {busy ? "…" : mode === "signup" ? "Create account & get started" : "Log in"}
          </button>
        </form>
        {error && <p style={{ color: "#b3261e", marginTop: 12 }}>{error}</p>}
        <p className="muted" style={{ marginTop: 14, fontSize: 13, lineHeight: 1.5 }}>
          Self-serve accounts mint free-tier keys (60 requests/min, up to 2 active).
          Need pro or enterprise volume?{" "}
          <a href="mailto:mohsin@boegroup.com">Email us</a>.
        </p>
      </div>
    );
  }

  return (
    <>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "baseline" }}>
        <p className="muted">Signed in as <b style={{ color: "var(--text)" }}>{me?.email ?? "…"}</b></p>
        <a href="#" className="muted" onClick={(e) => { e.preventDefault(); logout(); }}>Sign out</a>
      </div>
      {error && <p style={{ color: "#b3261e" }}>{error}</p>}

      {freshKey && (
        <div className="card" style={{ padding: 20, borderLeft: "4px solid var(--accent)", marginBottom: 18 }}>
          <b>Key “{freshKey.name}” created.</b> Copy it now — it is shown only once:
          <div style={{ display: "flex", gap: 10, alignItems: "center", marginTop: 10 }}>
            <code style={{ fontSize: 14, padding: "6px 10px", background: "var(--bg)",
                           borderRadius: 6, wordBreak: "break-all" }}>{freshKey.api_key}</code>
            <button className="btn secondary" onClick={() => {
              navigator.clipboard.writeText(freshKey.api_key).then(() => setCopied(true));
            }}>{copied ? "✓ Copied" : "Copy"}</button>
          </div>
        </div>
      )}

      <div className="card" style={{ padding: 20, marginBottom: 18 }}>
        <h3 style={{ marginTop: 0, color: "var(--navy)" }}>Your API keys</h3>
        {keys.length === 0 ? (
          <p className="muted">No keys yet — create your first one below.</p>
        ) : (
          <table>
            <thead>
              <tr>
                <th style={{ textAlign: "left" }}>Name</th>
                <th style={{ textAlign: "left" }}>Key</th>
                <th style={{ textAlign: "left" }}>Tier</th>
                <th className="num">Lifetime requests</th>
                <th style={{ textAlign: "left" }}>Status</th>
                <th></th>
              </tr>
            </thead>
            <tbody>
              {keys.map((k) => (
                <tr key={k.id} style={{ opacity: k.active ? 1 : 0.5 }}>
                  <td style={{ textAlign: "left" }}>{k.name}</td>
                  <td style={{ textAlign: "left" }}><code>{k.prefix}…</code></td>
                  <td style={{ textAlign: "left" }}>{k.tier}</td>
                  <td className="num">{k.requests.toLocaleString()}</td>
                  <td style={{ textAlign: "left" }}>{k.active ? "active" : "revoked"}</td>
                  <td className="num">
                    {k.active && (
                      <a href="#" className="muted"
                         onClick={(e) => { e.preventDefault(); revokeKey(k.id); }}>revoke</a>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
        <div style={{ display: "flex", gap: 10, marginTop: 14 }}>
          <input placeholder="Key name (e.g. backtest-runner)" value={newKeyName}
                 onChange={(e) => setNewKeyName(e.target.value)}
                 style={{ flex: 1, padding: 9, border: "1px solid var(--border)", borderRadius: 6 }} />
          <button className="btn" onClick={createKey}>Create key</button>
        </div>
      </div>

      <div className="card" style={{ padding: 20 }}>
        <h3 style={{ marginTop: 0, color: "var(--navy)" }}>Usage — last 30 days</h3>
        <UsageChart points={usage} />
        <p className="muted" style={{ fontSize: 13 }}>
          Total this period:{" "}
          <b style={{ color: "var(--text)" }}>
            {usage.reduce((s, p) => s + p.requests, 0).toLocaleString()}
          </b>{" "}
          requests across all keys. Counts update in real time as your keys are used.
        </p>
      </div>
    </>
  );
}
