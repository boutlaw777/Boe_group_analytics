import { randomBytes } from "crypto";
import { NextRequest, NextResponse } from "next/server";
import { z } from "zod";
import { getSupabase } from "@/lib/supabase";

export async function GET() {
  const supabase = getSupabase();
  const { data, error } = await supabase
    .from("api_keys")
    .select("id, key, tier, request_count, revoked, created_at")
    .order("created_at", { ascending: false });
  if (error) {
    return NextResponse.json({ error: error.message }, { status: 500 });
  }
  return NextResponse.json({ keys: data ?? [] });
}

const createSchema = z.object({
  tier: z.enum(["free", "pro"]).default("free"),
});

export async function POST(req: NextRequest) {
  let body: unknown = {};
  try {
    body = await req.json();
  } catch {
    // empty body is fine — defaults apply
  }
  const parsed = createSchema.safeParse(body ?? {});
  if (!parsed.success) {
    return NextResponse.json({ error: "tier must be 'free' or 'pro'" }, { status: 400 });
  }

  const key = `fc_${randomBytes(24).toString("hex")}`;

  const supabase = getSupabase();
  const { data, error } = await supabase
    .from("api_keys")
    .insert({ key, tier: parsed.data.tier })
    .select("id, key, tier, request_count, revoked, created_at")
    .single();
  if (error) {
    return NextResponse.json({ error: error.message }, { status: 500 });
  }
  return NextResponse.json({ apiKey: data }, { status: 201 });
}

export async function DELETE(req: NextRequest) {
  const id = req.nextUrl.searchParams.get("id");
  const parsed = z.string().uuid().safeParse(id);
  if (!parsed.success) {
    return NextResponse.json({ error: "id (uuid) required" }, { status: 400 });
  }

  const supabase = getSupabase();
  const { error } = await supabase
    .from("api_keys")
    .update({ revoked: true })
    .eq("id", parsed.data);
  if (error) {
    return NextResponse.json({ error: error.message }, { status: 500 });
  }
  return NextResponse.json({ ok: true });
}
