/* FinClone custom functions (PDR Module 2): =FINCLONE.VALUE(...)
 *
 * Runs in the custom-functions runtime (no DOM). Edit API_BASE if your
 * backend runs elsewhere — the backend must be served over HTTPS, because
 * Excel loads this runtime from an HTTPS origin and blocks mixed content.
 */
/* global CustomFunctions, OfficeRuntime */

const API_BASE = "https://localhost:8443";

// API key saved by the task pane (OfficeRuntime.storage is shared across runtimes)
async function authHeaders() {
  try {
    const key = await OfficeRuntime.storage.getItem("boe_api_key");
    return key ? { "X-API-Key": key } : {};
  } catch (e) {
    return {};
  }
}

/**
 * A financial value from the FinClone database.
 * @customfunction VALUE
 * @param {string} ticker Ticker symbol, e.g. "AAPL"
 * @param {string} concept Canonical concept, e.g. "revenue"
 * @param {number} year Fiscal year, e.g. 2024
 * @param {string} [period] "FY" (default), "Q1".."Q4"
 * @returns {number} The as-reported value.
 */
async function value(ticker, concept, year, period) {
  const fp = (period || "FY").toUpperCase();
  const url =
    `${API_BASE}/companies/${encodeURIComponent(ticker.toUpperCase())}/financials` +
    `?concept=${encodeURIComponent(concept.toLowerCase())}` +
    `&fiscal_year=${Math.round(year)}&point_in_time=latest`;

  let facts;
  try {
    const res = await fetch(url, { headers: await authHeaders() });
    if (res.status === 401) {
      throw new CustomFunctions.Error(CustomFunctions.ErrorCode.notAvailable,
        "Unauthorized — set your API key in the BOE Analytics task pane");
    }
    if (res.status === 429) {
      throw new CustomFunctions.Error(CustomFunctions.ErrorCode.notAvailable,
        "Rate limit exceeded — retry shortly");
    }
    if (res.status === 404) {
      throw new CustomFunctions.Error(CustomFunctions.ErrorCode.notAvailable,
        `${ticker} is not in the BOE Analytics database`);
    }
    if (!res.ok) {
      throw new CustomFunctions.Error(CustomFunctions.ErrorCode.notAvailable,
        `BOE Analytics API error ${res.status}`);
    }
    facts = await res.json();
  } catch (e) {
    if (e instanceof CustomFunctions.Error) throw e;
    throw new CustomFunctions.Error(CustomFunctions.ErrorCode.notAvailable,
      "BOE Analytics backend unreachable — is it running with HTTPS?");
  }

  // Annual balance-sheet values live at year-end (Q4)
  let fact = facts.find((f) => f.fiscal_period === fp);
  if (!fact && fp === "FY") fact = facts.find((f) => f.fiscal_period === "Q4");
  if (!fact) {
    throw new CustomFunctions.Error(CustomFunctions.ErrorCode.notAvailable,
      `No ${concept} for ${ticker} ${fp} ${year}`);
  }
  return fact.value;
}

CustomFunctions.associate("VALUE", value);
