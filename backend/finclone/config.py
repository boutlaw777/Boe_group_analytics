import os

from dotenv import load_dotenv

load_dotenv()

SEC_USER_AGENT = os.environ.get("SEC_USER_AGENT", "FinClone/0.1 (contact@example.com)")
DATABASE_URL = os.environ.get("DATABASE_URL", "sqlite:///./finclone.db")

# SEC fair-access policy: max 10 requests/sec. Stay just under it.
SEC_MIN_REQUEST_INTERVAL = 0.11

# LLM provider: DeepSeek (OpenAI-compatible API). Powers Scout, and KPI
# extraction unless a separate KPI provider is configured below.
DEEPSEEK_API_KEY = os.environ.get("DEEPSEEK_API_KEY", "")
DEEPSEEK_BASE_URL = os.environ.get("DEEPSEEK_BASE_URL", "https://api.deepseek.com")
KPI_MAX_CHUNKS = int(os.environ.get("FINCLONE_KPI_MAX_CHUNKS", "6"))

# Scout always runs on DeepSeek (kept separate from KPI_MODEL so routing KPIs
# to another provider can't send a foreign model name to DeepSeek's endpoint).
SCOUT_MODEL = os.environ.get("FINCLONE_SCOUT_MODEL", "deepseek-chat")

# KPI extraction provider. The bulk KPI sweep is thousands of LLM calls, so it
# can run on Gemini's free tier (OpenAI-compatible endpoint) to avoid spending
# DeepSeek credit. Set GEMINI_API_KEY to route KPI extraction through Gemini;
# Scout stays on DeepSeek for low interactive latency. Falls back to DeepSeek
# for KPIs when GEMINI_API_KEY is unset.
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")
_GEMINI_OPENAI_BASE = "https://generativelanguage.googleapis.com/v1beta/openai/"
if GEMINI_API_KEY:
    KPI_API_KEY = GEMINI_API_KEY
    KPI_BASE_URL = os.environ.get("KPI_BASE_URL", _GEMINI_OPENAI_BASE)
    KPI_MODEL = os.environ.get("FINCLONE_KPI_MODEL", "gemini-flash-lite-latest")
else:
    KPI_API_KEY = DEEPSEEK_API_KEY
    KPI_BASE_URL = DEEPSEEK_BASE_URL
    KPI_MODEL = os.environ.get("FINCLONE_KPI_MODEL", "deepseek-chat")

# Spend guard for bulk LLM work (added 2026-08-08, DeepSeek balance ~$10).
# The KPI_* fallback above is silent by design — convenient when DeepSeek had
# credit, dangerous now: with GEMINI_API_KEY unset, a KPI sweep or triage run
# quietly bills thousands of calls to the small prepaid DeepSeek balance and
# drains it long before the sweep finishes. Bulk entrypoints call
# require_bulk_provider() so that misconfiguration fails loudly at startup
# instead of showing up as an exhausted balance hours later. Scout is exempt —
# one call per user query is the volume profile DeepSeek is funded for.
ALLOW_DEEPSEEK_BULK = os.environ.get(
    "FINCLONE_ALLOW_DEEPSEEK_BULK", "").strip().lower() in ("1", "true", "yes")


def require_bulk_provider() -> None:
    """Refuse to start bulk LLM work on the paid DeepSeek account.

    Raises SystemExit when no KPI key is configured at all, or when KPI work
    would fall through to DeepSeek without an explicit opt-in.
    """
    if not KPI_API_KEY:
        raise SystemExit(
            "No KPI LLM key set. Add GEMINI_API_KEY (free tier) to backend\\.env")
    if KPI_API_KEY == DEEPSEEK_API_KEY and not ALLOW_DEEPSEEK_BULK:
        raise SystemExit(
            "Refusing to run bulk LLM work on DeepSeek.\n"
            "  GEMINI_API_KEY is unset, so KPI/triage calls would bill the "
            "prepaid DeepSeek balance — a full sweep costs far more than it "
            "holds, and draining it also takes Scout down.\n"
            "  Fix: set GEMINI_API_KEY in backend\\.env (free tier).\n"
            "  Override (spends real credit): FINCLONE_ALLOW_DEEPSEEK_BULK=true")


# Flag-triage stage 2 provider. Deliberately pinned to DeepSeek, decoupled
# from KPI_API_KEY/GEMINI_API_KEY above (2026-08-08): the user wants KPI
# extraction on the free Gemini tier but triage explanations to keep spending
# the paid DeepSeek balance — sharing KPI_API_KEY would silently drag triage
# onto Gemini too the moment GEMINI_API_KEY is set, which is exactly wrong for
# what was asked. Same reasoning as SCOUT_MODEL above, same fix.
TRIAGE_API_KEY = DEEPSEEK_API_KEY
TRIAGE_BASE_URL = DEEPSEEK_BASE_URL
TRIAGE_MODEL = os.environ.get("FINCLONE_TRIAGE_MODEL", "deepseek-chat")

# Runtime balance floor for flag triage (2026-08-08): "spend up to $10, then
# stop rather than run the account to zero again." DeepSeek has no native
# spend-limit setting reachable via API, so this is enforced from our side —
# checked periodically during the run via GET /user/balance, not a one-time
# check at startup, since the whole point is catching it mid-run before the
# balance is gone, not just at the first company.
DEEPSEEK_BALANCE_FLOOR = float(os.environ.get("FINCLONE_DEEPSEEK_BALANCE_FLOOR", "10"))


def deepseek_balance_remaining() -> float | None:
    """Current USD balance on the DeepSeek account, or None if the check
    itself failed. None must be treated as "unknown, proceed" by callers — a
    transient network hiccup on the balance endpoint is not a reason to halt
    a run that could otherwise keep going.
    """
    if not DEEPSEEK_API_KEY:
        return None
    import httpx
    try:
        resp = httpx.get(
            f"{DEEPSEEK_BASE_URL}/user/balance",
            headers={"Authorization": f"Bearer {DEEPSEEK_API_KEY}"}, timeout=10.0)
        resp.raise_for_status()
        for info in resp.json().get("balance_infos", []):
            if info.get("currency") == "USD":
                return float(info["total_balance"])
        return None
    except (httpx.HTTPError, KeyError, ValueError, TypeError):
        return None


def require_triage_provider() -> None:
    """Refuse to start bulk flag-triage on the paid DeepSeek account without
    an explicit opt-in — same FINCLONE_ALLOW_DEEPSEEK_BULK switch as
    require_bulk_provider, since both are "real money, thousands of calls"
    guards, but triage is never a Gemini candidate (its whole job is judgement
    a low-quality free model does poorly), so the message doesn't mention it.
    """
    if not TRIAGE_API_KEY:
        raise SystemExit("No DeepSeek key set. Add DEEPSEEK_API_KEY to backend\\.env")
    if not ALLOW_DEEPSEEK_BULK:
        raise SystemExit(
            "Refusing to run bulk flag triage on DeepSeek.\n"
            "  This bills the prepaid DeepSeek balance across every untriaged "
            "flag — deliberate, since triage needs real judgement, not the "
            "free tier.\n"
            "  Confirm the spend: FINCLONE_ALLOW_DEEPSEEK_BULK=true")


# Scout fallback provider. Scout is one interactive call per user query, not a
# bulk sweep — the opposite volume profile from KPI extraction, where Gemini's
# free-tier per-minute limit caused a multi-day stall. That history is exactly
# why this is its OWN variable rather than reusing GEMINI_API_KEY above:
# enabling this fallback must never flip KPI_API_KEY back to Gemini too.
# Deliberately separate from DEEPSEEK_API_KEY's outage mode as well — a
# DeepSeek balance/quota failure (the 2026-08-06 outage) is exactly the case
# this exists to survive, so it cannot depend on the same account.
SCOUT_FALLBACK_API_KEY = os.environ.get("SCOUT_FALLBACK_GEMINI_API_KEY", "")
SCOUT_FALLBACK_BASE_URL = os.environ.get("SCOUT_FALLBACK_GEMINI_BASE_URL", _GEMINI_OPENAI_BASE)
SCOUT_FALLBACK_MODEL = os.environ.get("SCOUT_FALLBACK_GEMINI_MODEL", "gemini-flash-lite-latest")

# Cross-reference validation (SimFin, per PDR §3)
SIMFIN_API_KEY = os.environ.get("SIMFIN_API_KEY", "")

# Raw-filing archive (Supabase Storage — fills the PDR's S3 role)
SUPABASE_URL = os.environ.get("SUPABASE_URL", "")
SUPABASE_SECRET_KEY = os.environ.get("SUPABASE_SECRET_KEY", "")
ARCHIVE_BUCKET = os.environ.get("FINCLONE_ARCHIVE_BUCKET", "filings")
CROSSREF_VARIANCE_THRESHOLD = float(os.environ.get("FINCLONE_VARIANCE_THRESHOLD", "0.01"))

# Stripe billing (PDR Module 5). Self-serve tier upgrades replace the previous
# admin-provisioned pro/enterprise keys. All optional — when STRIPE_SECRET_KEY
# is unset the /billing endpoints report "not configured" (503) and the rest of
# the API is unaffected, so the app runs fine before Stripe is wired up.
STRIPE_SECRET_KEY = os.environ.get("STRIPE_SECRET_KEY", "")
STRIPE_WEBHOOK_SECRET = os.environ.get("STRIPE_WEBHOOK_SECRET", "")
# Stripe Price IDs for each paid tier (create these in the Stripe dashboard).
STRIPE_PRICE_PRO = os.environ.get("STRIPE_PRICE_PRO", "")
STRIPE_PRICE_ENTERPRISE = os.environ.get("STRIPE_PRICE_ENTERPRISE", "")
# Where Stripe returns the user after checkout / billing-portal (your web app).
BILLING_SUCCESS_URL = os.environ.get(
    "FINCLONE_BILLING_SUCCESS_URL", "http://localhost:3000/account?checkout=success")
BILLING_CANCEL_URL = os.environ.get(
    "FINCLONE_BILLING_CANCEL_URL", "http://localhost:3000/account?checkout=cancel")

# Maps our tier name -> Stripe Price ID, and back. The webhook resolves an
# incoming Price ID to a tier; checkout resolves a tier to a Price ID.
STRIPE_PRICE_BY_TIER = {
    tier: price for tier, price in
    (("pro", STRIPE_PRICE_PRO), ("enterprise", STRIPE_PRICE_ENTERPRISE)) if price
}
TIER_BY_STRIPE_PRICE = {price: tier for tier, price in STRIPE_PRICE_BY_TIER.items()}
