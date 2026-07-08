/* FinClone task pane (PDR Module 2): ticker picker, Insert Model, Refresh. */
/* global Office, Excel */

const CONCEPT_ROWS = [
  ["Revenue", "revenue"],
  ["Cost of Revenue", "cost_of_revenue"],
  ["Gross Profit", "gross_profit"],
  ["R&D", "research_development"],
  ["SG&A", "sga_expense"],
  ["Operating Income", "operating_income"],
  ["Net Income", "net_income"],
  ["Diluted EPS", "eps_diluted"],
  ["Operating Cash Flow", "operating_cash_flow"],
  ["CapEx", "capex"],
  ["Total Assets", "total_assets"],
  ["Total Liabilities", "total_liabilities"],
  ["Stockholders' Equity", "stockholders_equity"],
];

const $ = (id) => document.getElementById(id);
const apiBase = () => $("api").value.trim().replace(/\/+$/, "");
const apiKey = () => $("apikey").value.trim();

function setStatus(text, cls) {
  const el = $("status");
  el.textContent = text;
  el.className = cls || "";
}

// Persist the key where the custom-functions runtime can also read it
async function saveApiKey() {
  try {
    await OfficeRuntime.storage.setItem("boe_api_key", apiKey());
  } catch (e) {
    /* storage unavailable in some hosts — pane still works via header below */
  }
}

async function getJSON(path) {
  const headers = {};
  if (apiKey()) headers["X-API-Key"] = apiKey();
  const res = await fetch(`${apiBase()}${path}`, { headers });
  if (res.status === 401) throw new Error("unauthorized — check your API key");
  if (res.status === 429) throw new Error("rate limit exceeded — try again shortly");
  if (!res.ok) throw new Error(`API ${res.status} on ${path}`);
  return res.json();
}

async function loadCompanies() {
  try {
    const companies = await getJSON("/companies");
    const select = $("ticker");
    select.innerHTML = "";
    for (const c of companies) {
      const opt = document.createElement("option");
      opt.value = c.ticker;
      opt.textContent = `${c.ticker} — ${c.name}`;
      select.appendChild(opt);
    }
    setStatus(`${companies.length} companies available`, "ok");
  } catch (e) {
    setStatus(`Cannot reach backend: ${e.message}`, "err");
  }
}

function pivot(facts, period) {
  // concept x period grid; annual uses FY (flows) / Q4 (year-end instants)
  const byKey = new Map();
  for (const f of facts) byKey.set(`${f.concept}|${f.fiscal_year}|${f.fiscal_period}`, f);
  const years = [...new Set(facts.map((f) => f.fiscal_year))].sort((a, b) => a - b).slice(-8);

  const columns = [];
  if (period === "annual") {
    for (const y of years) columns.push({ label: `FY${y}`, year: y, fp: "FY" });
  } else {
    for (const y of years)
      for (const q of ["Q1", "Q2", "Q3", "Q4"])
        if (facts.some((f) => f.fiscal_year === y && f.fiscal_period === q))
          columns.push({ label: `${q} FY${y}`, year: y, fp: q });
  }

  const cell = (concept, col) =>
    byKey.get(`${concept}|${col.year}|${col.fp}`) ??
    (col.fp === "FY" ? byKey.get(`${concept}|${col.year}|Q4`) : undefined);

  const header = ["Line item", ...columns.map((c) => c.label)];
  const rows = [];
  for (const [label, concept] of CONCEPT_ROWS) {
    if (!columns.some((c) => cell(concept, c))) continue;
    rows.push([label, ...columns.map((c) => cell(concept, c)?.value ?? "")]);
  }
  return { header, rows };
}

async function insertModel() {
  const ticker = $("ticker").value;
  const period = $("period").value;
  if (!ticker) return;
  setStatus("Fetching data…");
  try {
    const facts = await getJSON(`/companies/${ticker}/financials?point_in_time=latest`);
    const { header, rows } = pivot(facts, period);
    if (rows.length === 0) throw new Error("no data for this company");

    await Excel.run(async (ctx) => {
      const start = ctx.workbook.getSelectedRange().getCell(0, 0);
      const title = start.getResizedRange(0, 0);
      title.values = [[`${ticker} — BOE Analytics model (${period})`]];
      title.format.font.bold = true;

      const headerRange = start.getOffsetRange(1, 0).getResizedRange(0, header.length - 1);
      headerRange.values = [header];
      headerRange.format.font.bold = true;

      const body = start.getOffsetRange(2, 0).getResizedRange(rows.length - 1, header.length - 1);
      body.values = rows;

      // PDR formatting: as-reported numbers in blue, negatives in parentheses
      const numbers = start.getOffsetRange(2, 1).getResizedRange(rows.length - 1, header.length - 2);
      numbers.format.font.color = "#0B57D0";
      numbers.numberFormat = rows.map(() =>
        Array(header.length - 1).fill("#,##0;(#,##0)")
      );

      body.format.autofitColumns();
      await ctx.sync();
    });
    setStatus(`Inserted ${ticker} ${period} model (${rows.length} rows)`, "ok");
  } catch (e) {
    setStatus(`Insert failed: ${e.message}`, "err");
  }
}

async function refreshFormulas() {
  try {
    await Excel.run(async (ctx) => {
      ctx.workbook.application.calculate(Excel.CalculationType.fullRebuild);
      await ctx.sync();
    });
    setStatus("All BOE formulas recalculated", "ok");
  } catch (e) {
    setStatus(`Refresh failed: ${e.message}`, "err");
  }
}

/* global OfficeRuntime */
Office.onReady(async () => {
  $("insert").onclick = insertModel;
  $("refresh").onclick = refreshFormulas;
  $("api").onchange = loadCompanies;
  $("apikey").onchange = async () => { await saveApiKey(); loadCompanies(); };
  try {
    const saved = await OfficeRuntime.storage.getItem("boe_api_key");
    if (saved) $("apikey").value = saved;
  } catch (e) { /* first run / storage unavailable */ }
  loadCompanies();
});
