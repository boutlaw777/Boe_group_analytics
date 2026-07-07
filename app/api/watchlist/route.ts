import { NextRequest, NextResponse } from "next/server";
import { z } from "zod";
import { getSupabase } from "@/lib/supabase";

export async function GET() {
  const supabase = getSupabase();
  const { data, error } = await supabase
    .from("watchlist")
    .select("id, added_at, companies (id, ticker, name, sector, industry)")
    .order("added_at", { ascending: false });
  if (error) {
    return NextResponse.json({ error: error.message }, { status: 500 });
  }
  return NextResponse.json({ watchlist: data ?? [] });
}

const addSchema = z.object({ companyId: z.string().uuid() });

export async function POST(req: NextRequest) {
  let body: unknown;
  try {
    body = await req.json();
  } catch {
    return NextResponse.json({ error: "Invalid JSON body" }, { status: 400 });
  }
  const parsed = addSchema.safeParse(body);
  if (!parsed.success) {
    return NextResponse.json({ error: "companyId (uuid) required" }, { status: 400 });
  }

  const supabase = getSupabase();
  const { data, error } = await supabase
    .from("watchlist")
    .upsert({ company_id: parsed.data.companyId }, { onConflict: "company_id" })
    .select("id, company_id, added_at")
    .single();
  if (error) {
    return NextResponse.json({ error: error.message }, { status: 500 });
  }
  return NextResponse.json({ entry: data }, { status: 201 });
}

export async function DELETE(req: NextRequest) {
  const companyId = req.nextUrl.searchParams.get("companyId");
  const parsed = z.string().uuid().safeParse(companyId);
  if (!parsed.success) {
    return NextResponse.json({ error: "companyId (uuid) required" }, { status: 400 });
  }

  const supabase = getSupabase();
  const { error } = await supabase
    .from("watchlist")
    .delete()
    .eq("company_id", parsed.data);
  if (error) {
    return NextResponse.json({ error: error.message }, { status: 500 });
  }
  return NextResponse.json({ ok: true });
}
