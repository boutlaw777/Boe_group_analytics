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
