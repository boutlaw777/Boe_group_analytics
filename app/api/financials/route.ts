import { NextRequest, NextResponse } from "next/server";
import { z } from "zod";
import { getFinancials } from "@/lib/financials";
import { SimFinError } from "@/lib/simfin";

const querySchema = z.object({
  ticker: z
    .string()
    .trim()
    .min(1, "ticker is required")
    .max(10)
    .regex(/^[A-Za-z.\-]+$/, "invalid ticker format"),
  period: z.enum(["FY", "Q1", "Q2", "Q3", "Q4"]).default("FY"),
  fyear: z.coerce.number().int().min(1990).max(2100),
});

export async function GET(req: NextRequest) {
  const params = req.nextUrl.searchParams;
  const parsed = querySchema.safeParse({
    ticker: params.get("ticker") ?? "",
    period: params.get("period") ?? "FY",
    fyear: params.get("fyear"),
  });
  if (!parsed.success) {
    return NextResponse.json(
      { error: parsed.error.issues[0].message },
      { status: 400 }
    );
  }

  const { ticker, period, fyear } = parsed.data;

  try {
    const result = await getFinancials(ticker, period, fyear);
    if (!result) {
      return NextResponse.json(
        { error: `No company found for ticker "${ticker.toUpperCase()}"` },
        { status: 404 }
      );
    }
    return NextResponse.json({
      company: result.company,
      financials: result.rows,
      fromCache: result.fromCache,
      warning: result.warning ?? null,
    });
  } catch (err) {
    if (err instanceof SimFinError) {
      return NextResponse.json(
        { error: err.message },
        { status: err.rateLimited ? 429 : 502 }
      );
    }
    console.error("financials route error:", err);
    return NextResponse.json({ error: "Internal server error" }, { status: 500 });
  }
}
