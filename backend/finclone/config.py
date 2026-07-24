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

# Cross-reference validation (SimFin, per PDR §3)
SIMFIN_API_KEY = os.environ.get("SIMFIN_API_KEY", "")

# Raw-filing archive (Supabase Storage — fills the PDR's S3 role)
SUPABASE_URL = os.environ.get("SUPABASE_URL", "")
SUPABASE_SECRET_KEY = os.environ.get("SUPABASE_SECRET_KEY", "")
ARCHIVE_BUCKET = os.environ.get("FINCLONE_ARCHIVE_BUCKET", "filings")
CROSSREF_VARIANCE_THRESHOLD = float(os.environ.get("FINCLONE_VARIANCE_THRESHOLD", "0.01"))
