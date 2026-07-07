import { NextRequest, NextResponse } from "next/server";
import { z } from "zod";
import { authenticateApiRequest } from "@/lib/apiAuth";
import { getSupabase } from "@/lib/supabase";

const KEY_METRICS = ["Revenue", "Gross Profit", "Operating Income (Loss)", "Net Income"];

const querySchema = z.object({
  sector: z.string().trim().min(1, "sector is required").max(100),
});

export async function GET(req: NextRequest) {
  const auth = await authenticateApiRequest(req);
  if (!auth.ok) return auth.response;

  const parsed = querySchema.safeParse({
    sector: req.nextUrl.searchParams.get("sector") ?? "",
  });
  if (!parsed.success) {
    return NextResponse.json(
      { error: parsed.error.issues[0].message },
      { status: 400 }
    );
  }

  const supabase = getSupabase();
  const { data, error } = await supabase
    .from("financials")
    .select(
      "line_item, value, fiscal_year, companies!inner(ticker, name, sector, industry)"
    )
    .eq("period", "FY")
    .in("line_item", KEY_METRICS)
    .not("value", "is", null)
    .or(
      `sector.ilike.%${parsed.data.sector}%,industry.ilike.%${parsed.data.sector}%`,
      { referencedTable: "companies" }
    );
  if (error) {
    return NextResponse.json({ error: error.message }, { status: 500 });
  }

  interface Row {
    line_item: string;
    value: number;
    fiscal_year: number;
    companies: { ticker: string; name: string; sector: string | null; industry: string | null };
  }
  const rows = (data ?? []) as unknown as Row[];

  // Latest fiscal year per (company, metric).
  const byCompany = new Map<
    string,
    { name: string; sector: string | null; industry: string | null; metrics: Record<string, { value: number; fiscal_year: number }> }
  >();
  for (const row of rows) {
    const key = row.companies.ticker;
    if (!byCompany.has(key)) {
      byCompany.set(key, {
        name: row.companies.name,
        sector: row.companies.sector,
        industry: row.companies.industry,
        metrics: {},
      });
    }
    const entry = byCompany.get(key)!;
    const existing = entry.metrics[row.line_item];
    if (!existing || row.fiscal_year > existing.fiscal_year) {
      entry.metrics[row.line_item] = { value: row.value, fiscal_year: row.fiscal_year };
    }
  }

  return NextResponse.json({
    sector: parsed.data.sector,
    companies: [...byCompany.entries()].map(([ticker, c]) => ({
      ticker,
      name: c.name,
      sector: c.sector,
      industry: c.industry,
      metrics: c.metrics,
    })),
  });
}
