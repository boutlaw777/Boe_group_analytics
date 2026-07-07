import { getFinancials } from "./lib/financials";

getFinancials("AAPL", "FY", 2025)
  .then((r) => {
    console.log("OK — fromCache:", r?.fromCache, "rows:", r?.rows.length, "warning:", r?.warning);
  })
  .catch((err) => {
    console.error("FAILED:", err);
  });
