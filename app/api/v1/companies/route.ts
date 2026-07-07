import { NextRequest, NextResponse } from "next/server";
import { authenticateApiRequest } from "@/lib/apiAuth";
import { getSupabase } from "@/lib/supabase";

export async function GET(req: NextRequest) {
  const auth = await authenticateApiRequest(req);
  if (!auth.ok) return auth.response;

  const supabase = getSupabase();
  const { data, error } = await supabase
    .from("companies")
    .select("id, ticker, name, sector, industry, simfin_id")
    .order("ticker");
  if (error) {
    return NextResponse.json({ error: error.message }, { status: 500 });
  }
  return NextResponse.json({ companies: data ?? [] });
}
