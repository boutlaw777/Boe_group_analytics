/**
 * Developer API auth: Bearer key validation against the api_keys table,
 * plus simple in-memory per-minute rate limiting by tier.
 */
import { NextRequest, NextResponse } from "next/server";
import { getSupabase } from "./supabase";

const RATE_LIMITS: Record<string, number> = {
  free: 10, // requests per minute
  pro: 60,
};

interface WindowCounter {
  windowStart: number;
  count: number;
}

// In-memory counters — reset on server restart / per serverless instance.
// Fine for this phase per spec; move to Redis/Upstash for production.
const counters = new Map<string, WindowCounter>();

export interface ApiKeyRecord {
  id: string;
  key: string;
  tier: string;
}

export type AuthResult =
  | { ok: true; apiKey: ApiKeyRecord }
  | { ok: false; response: NextResponse };

export async function authenticateApiRequest(
  req: NextRequest
): Promise<AuthResult> {
  const header = req.headers.get("authorization") ?? "";
  const match = header.match(/^Bearer\s+(.+)$/i);
  if (!match) {
    return {
      ok: false,
      response: NextResponse.json(
        { error: "Missing Authorization: Bearer <api_key> header" },
        { status: 401 }
      ),
    };
  }
  const key = match[1].trim();

  const supabase = getSupabase();
  const { data, error } = await supabase
    .from("api_keys")
    .select("id, key, tier, revoked")
    .eq("key", key)
    .maybeSingle();
  if (error) {
    return {
      ok: false,
      response: NextResponse.json(
        { error: "Key validation failed" },
        { status: 500 }
      ),
    };
  }
  if (!data || data.revoked) {
    return {
      ok: false,
      response: NextResponse.json(
        { error: "Invalid or revoked API key" },
        { status: 401 }
      ),
    };
  }

  // ---- rate limit (per key, per minute, by tier)
  const limit = RATE_LIMITS[data.tier] ?? RATE_LIMITS.free;
  const now = Date.now();
  const counter = counters.get(key);
  if (!counter || now - counter.windowStart >= 60_000) {
    counters.set(key, { windowStart: now, count: 1 });
  } else {
    counter.count += 1;
    if (counter.count > limit) {
      const retryAfter = Math.ceil((counter.windowStart + 60_000 - now) / 1000);
      return {
        ok: false,
        response: NextResponse.json(
          {
            error: `Rate limit exceeded (${limit} requests/min on the '${data.tier}' tier)`,
          },
          { status: 429, headers: { "Retry-After": String(retryAfter) } }
        ),
      };
    }
  }

  // Track usage (fire-and-forget; don't block the request on it).
  // Requires the increment_api_key_count() function from supabase/schema.sql.
  void supabase
    .rpc("increment_api_key_count", { key_id: data.id })
    .then(({ error: rpcError }) => {
      if (rpcError) console.error("api key count update failed:", rpcError.message);
    });

  return { ok: true, apiKey: { id: data.id, key: data.key, tier: data.tier } };
}
