import { NextRequest, NextResponse } from "next/server";
import { z } from "zod";
import { authenticateApiRequest } from "@/lib/apiAuth";
import { getFinancials } from "@/lib/financials";
import { SimFinError, type FiscalPeriod } from "@/lib/simfin";

export const maxDuration = 60;

const querySchema = z.object({
  ticker: z
    .string()
    .trim()
    .min(1, "ticker is required")
    .max(10)
    .regex(/^[A-Za-z.\-]+$/, "invalid ticker format"),
  year: z.coerce.number().int().min(1990).max(2100),
  quarter: z.enum(["Q1", "Q2", "Q3", "Q4"]).optional(),
});

export async function GET(req: NextRequest) {
  const auth = await authenticateApiRequest(req);
  if (!auth.ok) return auth.response;

  const params = req.nextUrl.searchParams;
  const parsed = querySchema.safeParse({
    ticker: params.get("ticker") ?? "",
    year: params.get("year"),
    quarter: params.get("quarter") ?? undefined,
  });
  if (!parsed.success) {
    return NextResponse.json(
      { error: parsed.error.issues[0].message },
      { status: 400 }
    );
  }

  const period: FiscalPeriod = parsed.data.quarter ?? "FY";

  try {
    const result = await getFinancials(parsed.data.ticker, period, parsed.data.year);
    if (!result) {
      return NextResponse.json(
        { error: `Unknown ticker "${parsed.data.ticker.toUpperCase()}"` },
        { status: 404 }
      );
    }
    return NextResponse.json({
      company: {
        ticker: result.company.ticker,
        name: result.company.name,
        sector: result.company.sector,
        industry: result.company.industry,
      },
      period,
      fiscal_year: parsed.data.year,
      financials: result.rows.map((r) => ({
        line_item: r.line_item,
        value: r.value,
        is_hardcoded: r.is_hardcoded,
        source_url: r.source_url,
      })),
    });
  } catch (err) {
    if (err instanceof SimFinError) {
      return NextResponse.json(
        { error: err.message },
        { status: err.rateLimited ? 429 : 502 }
      );
    }
    console.error("v1/financials error:", err);
    return NextResponse.json({ error: "Internal server error" }, { status: 500 });
  }
}
