import { NextRequest, NextResponse } from "next/server";
import { z } from "zod";
import {
  parseScreenQuery,
  screenCompanies,
  type ScreenFilter,
} from "@/lib/scout";

export const maxDuration = 60;

const filterSchema = z.object({
  sector: z.string().max(100).nullable(),
  metric: z.string().min(1).max(200),
  isGrowth: z.boolean(),
  operator: z.enum([">", "<", ">=", "<=", "="]),
  value: z.number(),
  fiscalYear: z.number().int().min(1990).max(2100).nullable(),
});

// Either a natural-language query to interpret, or a fully-specified filter
// to run directly (used when the user confirms a threshold we asked for).
const bodySchema = z
  .object({
    query: z.string().trim().min(3).max(500).optional(),
    filter: filterSchema.optional(),
  })
  .refine((b) => b.query || b.filter, {
    message: "Provide a query or a filter",
  });

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

  try {
    // Direct filter run — no interpretation needed.
    if (parsed.data.filter) {
      const filter = parsed.data.filter as ScreenFilter;
      const results = await screenCompanies(filter);
      return NextResponse.json({
        kind: "results",
        filter,
        results,
        note: results.length === 0 ? EMPTY_UNIVERSE_NOTE : null,
      });
    }

    const intent = await parseScreenQuery(parsed.data.query!);

    // Guardrail 1: single-company questions are lookups, not screens —
    // route the user to the Overview view instead of running a screen.
    if (intent.queryType === "lookup" && intent.ticker) {
      return NextResponse.json({
        kind: "lookup",
        ticker: intent.ticker.toUpperCase(),
        metric: intent.metric,
        fiscalYear: intent.fiscalYear,
      });
    }

    // Guardrail 2: the query names a metric but no threshold — ask for one
    // instead of silently screening against an invented value.
    if (intent.operator === null || intent.value === null) {
      return NextResponse.json({
        kind: "needs_threshold",
        filter: {
          sector: intent.sector,
          metric: intent.metric,
          isGrowth: intent.isGrowth,
          fiscalYear: intent.fiscalYear,
        },
      });
    }

    const filter: ScreenFilter = {
      sector: intent.sector,
      metric: intent.metric,
      isGrowth: intent.isGrowth,
      operator: intent.operator,
      value: intent.value,
      fiscalYear: intent.fiscalYear,
    };
    const results = await screenCompanies(filter);
    return NextResponse.json({
      kind: "results",
      filter,
      results,
      note: results.length === 0 ? EMPTY_UNIVERSE_NOTE : null,
    });
  } catch (err) {
    console.error("scout route error:", err);
    const message =
      err instanceof Error ? err.message : "Scout search failed";
    return NextResponse.json({ error: message }, { status: 500 });
  }
}

const EMPTY_UNIVERSE_NOTE =
  "No matches in the cached universe. Scout screens companies already loaded into the cache — search tickers on the Overview page to add more.";
