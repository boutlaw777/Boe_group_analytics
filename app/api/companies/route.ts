import { NextRequest, NextResponse } from "next/server";
import { z } from "zod";
import { getOrCreateCompany } from "@/lib/financials";
import { SimFinError } from "@/lib/simfin";

const querySchema = z.object({
  ticker: z
    .string()
    .trim()
    .min(1, "ticker is required")
    .max(10)
    .regex(/^[A-Za-z.\-]+$/, "invalid ticker format"),
});

export async function GET(req: NextRequest) {
  const parsed = querySchema.safeParse({
    ticker: req.nextUrl.searchParams.get("ticker") ?? "",
  });
  if (!parsed.success) {
    return NextResponse.json(
      { error: parsed.error.issues[0].message },
      { status: 400 }
    );
  }

  try {
    const company = await getOrCreateCompany(parsed.data.ticker);
    if (!company) {
      return NextResponse.json(
        { error: `No company found for ticker "${parsed.data.ticker.toUpperCase()}"` },
        { status: 404 }
      );
    }
    return NextResponse.json({ company });
  } catch (err) {
    if (err instanceof SimFinError) {
      return NextResponse.json(
        { error: err.message },
        { status: err.rateLimited ? 429 : 502 }
      );
    }
    console.error("companies route error:", err);
    return NextResponse.json({ error: "Internal server error" }, { status: 500 });
  }
}
