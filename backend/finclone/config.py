import os

from dotenv import load_dotenv

load_dotenv()

SEC_USER_AGENT = os.environ.get("SEC_USER_AGENT", "FinClone/0.1 (contact@example.com)")
DATABASE_URL = os.environ.get("DATABASE_URL", "sqlite:///./finclone.db")

# SEC fair-access policy: max 10 requests/sec. Stay just under it.
SEC_MIN_REQUEST_INTERVAL = 0.11

# LLM provider: DeepSeek (OpenAI-compatible API)
DEEPSEEK_API_KEY = os.environ.get("DEEPSEEK_API_KEY", "")
DEEPSEEK_BASE_URL = os.environ.get("DEEPSEEK_BASE_URL", "https://api.deepseek.com")
KPI_MODEL = os.environ.get("FINCLONE_KPI_MODEL", "deepseek-chat")
KPI_MAX_CHUNKS = int(os.environ.get("FINCLONE_KPI_MAX_CHUNKS", "6"))

# Cross-reference validation (SimFin, per PDR §3)
SIMFIN_API_KEY = os.environ.get("SIMFIN_API_KEY", "")

# Raw-filing archive (Supabase Storage — fills the PDR's S3 role)
SUPABASE_URL = os.environ.get("SUPABASE_URL", "")
SUPABASE_SECRET_KEY = os.environ.get("SUPABASE_SECRET_KEY", "")
ARCHIVE_BUCKET = os.environ.get("FINCLONE_ARCHIVE_BUCKET", "filings")
CROSSREF_VARIANCE_THRESHOLD = float(os.environ.get("FINCLONE_VARIANCE_THRESHOLD", "0.01"))
