"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";

export default function SearchBox() {
  const router = useRouter();
  const [ticker, setTicker] = useState("");

  return (
    <form
      className="search-row"
      onSubmit={(e) => {
        e.preventDefault();
        const t = ticker.trim().toUpperCase();
        if (t) router.push(`/company/${t}`);
      }}
    >
      <input
        value={ticker}
        onChange={(e) => setTicker(e.target.value)}
        placeholder="Search ticker, e.g. AAPL"
        aria-label="Ticker search"
      />
      <button type="submit">Open</button>
    </form>
  );
}
