"use client";
import { useEffect, useState } from "react";

const KEY = "boe_watchlist";

export function readWatchlist(): string[] {
  try {
    return JSON.parse(localStorage.getItem(KEY) ?? "[]");
  } catch {
    return [];
  }
}

export function writeWatchlist(tickers: string[]) {
  localStorage.setItem(KEY, JSON.stringify([...new Set(tickers)].sort()));
}

/** Buttons under a Scout result set: save the screened tickers to the
 *  watchlist, or bulk-download their Data Sheets as a zip (PDR Module 3). */
export function WatchlistActions({ apiBase, tickers }: { apiBase: string; tickers: string[] }) {
  const [saved, setSaved] = useState(false);
  if (tickers.length === 0) return null;

  const addAll = () => {
    writeWatchlist([...readWatchlist(), ...tickers]);
    setSaved(true);
    setTimeout(() => setSaved(false), 2000);
  };

  return (
    <p>
      <a className="btn secondary" href="#" onClick={(e) => { e.preventDefault(); addAll(); }}>
        {saved ? "✓ Saved" : `Save ${tickers.length} to Watchlist`}
      </a>{" "}
      <a className="btn" href={`${apiBase}/datasheets?tickers=${tickers.join(",")}`}>
        Download all Data Sheets (.zip)
      </a>
    </p>
  );
}

/** The /watchlist page body: saved tickers with remove + bulk download. */
export function WatchlistView({ apiBase }: { apiBase: string }) {
  const [tickers, setTickers] = useState<string[]>([]);
  const [loaded, setLoaded] = useState(false);

  useEffect(() => {
    setTickers(readWatchlist());
    setLoaded(true);
  }, []);

  const remove = (t: string) => {
    const next = tickers.filter((x) => x !== t);
    writeWatchlist(next);
    setTickers(next);
  };

  if (!loaded) return null;
  if (tickers.length === 0)
    return <p className="muted">Your watchlist is empty — screen companies in Scout and save the results.</p>;

  return (
    <>
      <div className="card" style={{ padding: 0 }}>
        <table>
          <thead>
            <tr><th style={{ textAlign: "left" }}>Ticker</th><th></th></tr>
          </thead>
          <tbody>
            {tickers.map((t) => (
              <tr key={t}>
                <td style={{ textAlign: "left" }}>
                  <a href={`/company/${t}`}><b>{t}</b></a>
                </td>
                <td className="num">
                  <a href="#" className="muted" onClick={(e) => { e.preventDefault(); remove(t); }}>
                    remove
                  </a>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <p>
        <a className="btn" href={`${apiBase}/datasheets?tickers=${tickers.join(",")}`}>
          Download all Data Sheets (.zip)
        </a>
      </p>
    </>
  );
}
