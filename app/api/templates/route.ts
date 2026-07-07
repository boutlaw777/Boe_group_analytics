import { NextRequest, NextResponse } from "next/server";
import { z } from "zod";
import { getSupabase } from "@/lib/supabase";

const formulaTokenSchema = z.object({
  type: z.enum(["item", "op", "number"]),
  value: z.string().min(1).max(200),
});

const createSchema = z.object({
  name: z.string().trim().min(1).max(100),
  rowMapping: z.array(z.string().min(1).max(200)).max(500).default([]),
  customFormulas: z
    .array(
      z.object({
        name: z.string().trim().min(1).max(100),
        tokens: z.array(formulaTokenSchema).min(1).max(50),
      })
    )
    .max(50)
    .default([]),
});

export async function GET() {
  const supabase = getSupabase();
  const { data, error } = await supabase
    .from("templates")
    .select("id, name, row_mapping_json, custom_formulas_json, created_at")
    .order("created_at", { ascending: false });
  if (error) {
    return NextResponse.json({ error: error.message }, { status: 500 });
  }
  return NextResponse.json({ templates: data ?? [] });
}

export async function POST(req: NextRequest) {
  let body: unknown;
  try {
    body = await req.json();
  } catch {
    return NextResponse.json({ error: "Invalid JSON body" }, { status: 400 });
  }

  const parsed = createSchema.safeParse(body);
  if (!parsed.success) {
    return NextResponse.json(
      { error: parsed.error.issues[0].message },
      { status: 400 }
    );
  }

  const supabase = getSupabase();
  const { data, error } = await supabase
    .from("templates")
    .insert({
      name: parsed.data.name,
      row_mapping_json: parsed.data.rowMapping,
      custom_formulas_json: parsed.data.customFormulas,
    })
    .select("id, name, row_mapping_json, custom_formulas_json, created_at")
    .single();
  if (error) {
    return NextResponse.json({ error: error.message }, { status: 500 });
  }
  return NextResponse.json({ template: data }, { status: 201 });
}
