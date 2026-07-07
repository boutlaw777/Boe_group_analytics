import { NextRequest, NextResponse } from "next/server";
import { z } from "zod";
import { getSupabase } from "@/lib/supabase";

export async function DELETE(
  _req: NextRequest,
  { params }: { params: { id: string } }
) {
  const parsed = z.string().uuid().safeParse(params.id);
  if (!parsed.success) {
    return NextResponse.json({ error: "Invalid template id" }, { status: 400 });
  }

  const supabase = getSupabase();
  const { error } = await supabase.from("templates").delete().eq("id", parsed.data);
  if (error) {
    return NextResponse.json({ error: error.message }, { status: 500 });
  }
  return NextResponse.json({ ok: true });
}
