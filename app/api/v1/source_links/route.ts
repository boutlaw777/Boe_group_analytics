import { NextRequest, NextResponse } from "next/server";
import { z } from "zod";
import { authenticateApiRequest } from "@/lib/apiAuth";
import { getSupabase } from "@/lib/supabase";

const querySchema = z.object({
  ticker: z
    .string()
    .trim()
    .min(1, "ticker is required")
    .max(10)
    .regex(/^[A-Za-z.\-]+$/, "invalid ticker format"),
});

export async function GET(req: NextRequest) {
  const auth = await authenticateApiRequest(req);
  if (!auth.ok) return auth.response;

  const parsed = querySchema.safeParse({
    ticker: req.nextUrl.searchParams.get("ticker") ?? "",
  });
  if (!parsed.success) {
    return NextResponse.json(
      { error: parsed.error.issues[0].message },
      { status: 400 }
    );
  }

  const supabase = getSupabase();
  const ticker = parsed.data.ticker.toUpperCase();

  const { data: company, error: companyError } = await supabase
    .from("companies")
    .select("id, ticker, name")
    .eq("ticker", ticker)
    .maybeSingle();
  if (companyError) {
    return NextResponse.json({ error: companyError.message }, { status: 500 });
  }
  if (!company) {
    return NextResponse.json(
      { error: `Ticker "${ticker}" not found in cache. Fetch it via /api/v1/financials first.` },
      { status: 404 }
    );
  }

  const { data, error } = await supabase
    .from("financials")
    .select("line_item, period, fiscal_year, source_url")
    .eq("company_id", company.id)
    .not("source_url", "is", null)
    .order("fiscal_year", { ascending: false })
    .order("line_item");
  if (error) {
    return NextResponse.json({ error: error.message }, { status: 500 });
  }

  return NextResponse.json({
    company: { ticker: company.ticker, name: company.name },
    // SimFin provides one source per statement/period (an SEC EDGAR filing
    // index page), shared by all line items on that statement — links are
    // NOT anchored to the exact disclosure of each value.
    granularity: "filing",
    source_links: data ?? [],
  });
}
