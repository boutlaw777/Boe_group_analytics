import { NextRequest, NextResponse } from "next/server";
import { z } from "zod";
import { getFinancials, type FinancialRow } from "@/lib/financials";
import { buildDataSheetWorkbook, type TemplateConfig } from "@/lib/excel";
import { getSupabase } from "@/lib/supabase";
import { SimFinError } from "@/lib/simfin";

export const runtime = "nodejs";
export const maxDuration = 60; // multiple SimFin fetches on cold cache

const bodySchema = z.object({
  ticker: z
    .string()
    .trim()
    .min(1)
    .max(10)
    .regex(/^[A-Za-z.\-]+$/, "invalid ticker format"),
  period: z.enum(["FY", "Q1", "Q2", "Q3", "Q4"]).default("FY"),
  years: z.array(z.coerce.number().int().min(1990).max(2100)).min(1).max(10),
  /** Empty or omitted = include every available line item. */
  lineItems: z.array(z.string().min(1).max(200)).max(500).optional(),
  templateId: z.string().uuid().optional(),
  units: z.enum(["raw", "millions", "billions"]).default("raw"),
});

const formulaTokenSchema = z.object({
  type: z.enum(["item", "op", "number"]),
  value: z.string().min(1).max(200),
});

async function loadTemplate(templateId: string): Promise<TemplateConfig | null> {
  const supabase = getSupabase();
  const { data, error } = await supabase
    .from("templates")
    .select("name, row_mapping_json, custom_formulas_json")
    .eq("id", templateId)
    .maybeSingle();
  if (error) throw new Error(`Supabase template load failed: ${error.message}`);
  if (!data) return null;

  const rowMapping = z.array(z.string()).catch([]).parse(data.row_mapping_json);
  const customFormulas = z
    .array(z.object({ name: z.string(), tokens: z.array(formulaTokenSchema) }))
    .catch([])
    .parse(data.custom_formulas_json);

  return { name: data.name, rowMapping, customFormulas };
}

export async function POST(req: NextRequest) {
  let body: unknown;
  try {
    body = await req.json();
  } catch {
    return NextResponse.json({ error: "Invalid JSON body" }, { status: 400 });
  }

  const parsed = bodySchema.safeParse(body);
  if (!parsed.success) {
    return NextResponse.json(
      { error: parsed.error.issues[0].message },
      { status: 400 }
    );
  }
  const { ticker, period, templateId } = parsed.data;
  const years = [...new Set(parsed.data.years)].sort((a, b) => a - b);

  try {
    // Gather data year by year (cache-first; sequential to respect SimFin limits).
    const allRows: FinancialRow[] = [];
    let company = null;
    let warning: string | undefined;

    for (const year of years) {
      const result = await getFinancials(ticker, period, year);
      if (!result) {
        return NextResponse.json(
          { error: `No company found for ticker "${ticker.toUpperCase()}"` },
          { status: 404 }
        );
      }
      company = result.company;
      warning = warning ?? result.warning;
      allRows.push(...result.rows);
    }
    if (!company) {
      return NextResponse.json({ error: "No data found" }, { status: 404 });
    }

    // Which line items to include (preserve natural statement order).
    const available: string[] = [];
    const seen = new Set<string>();
    for (const row of allRows) {
      if (!seen.has(row.line_item)) {
        seen.add(row.line_item);
        available.push(row.line_item);
      }
    }
    const requested = parsed.data.lineItems?.length
      ? new Set(parsed.data.lineItems)
      : null;
    const lineItems = requested
      ? available.filter((li) => requested.has(li))
      : available;

    if (lineItems.length === 0) {
      return NextResponse.json(
        { error: "No matching line items found for the selected years." },
        { status: 404 }
      );
    }

    const template = templateId ? await loadTemplate(templateId) : null;

    const buffer = await buildDataSheetWorkbook({
      company,
      period,
      years,
      lineItems,
      rows: allRows,
      template,
      units: parsed.data.units,
    });

    const filename = `${company.ticker}_${period}_${years[0]}-${years[years.length - 1]}.xlsx`;
    return new NextResponse(Buffer.from(buffer as ArrayBuffer), {
      headers: {
        "Content-Type":
          "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        "Content-Disposition": `attachment; filename="${filename}"`,
        ...(warning ? { "X-BOE-Analytics-Warning": warning } : {}),
      },
    });
  } catch (err) {
    if (err instanceof SimFinError) {
      return NextResponse.json(
        { error: err.message },
        { status: err.rateLimited ? 429 : 502 }
      );
    }
    console.error("excel route error:", err);
    return NextResponse.json({ error: "Internal server error" }, { status: 500 });
  }
}
