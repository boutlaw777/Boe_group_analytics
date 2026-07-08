"""API-key authentication and tier-based rate limiting (PDR Phase 4).

Keys are stored as SHA-256 hashes — the raw key is shown exactly once at
creation. Rate limits are enforced per key with a 60-second sliding window,
sized by subscription tier. The in-memory limiter is per-process (fine for a
single uvicorn worker; move the window state to Redis when scaling out).

Enforcement is off by default for local development. Set
FINCLONE_REQUIRE_API_KEY=true to protect the data endpoints, and
FINCLONE_ADMIN_TOKEN to enable the /admin/keys management endpoints.
"""

import hashlib
import os
import secrets
import time
from collections import deque

TIER_LIMITS: dict[str, int] = {  # requests per minute
    "free": 60,
    "pro": 600,
    "enterprise": 6000,
}

_WINDOW_SECONDS = 60.0


def require_enabled() -> bool:
    return os.environ.get("FINCLONE_REQUIRE_API_KEY", "").lower() in ("1", "true", "yes")


def admin_token() -> str:
    return os.environ.get("FINCLONE_ADMIN_TOKEN", "")


def generate_key() -> str:
    return "boe_" + secrets.token_urlsafe(24)


def hash_key(raw: str) -> str:
    return hashlib.sha256(raw.encode()).hexdigest()


class RateLimiter:
    """Sliding-window limiter: at most TIER_LIMITS[tier] requests per minute."""

    def __init__(self, limits: dict[str, int]):
        self.limits = limits
        self._hits: dict[str, deque[float]] = {}

    def check(self, key_id: str, tier: str, now: float | None = None) -> float | None:
        """None if the request is allowed (and recorded); otherwise the number
        of seconds until a slot frees up."""
        limit = self.limits.get(tier, self.limits["free"])
        now = time.monotonic() if now is None else now
        hits = self._hits.setdefault(key_id, deque())
        cutoff = now - _WINDOW_SECONDS
        while hits and hits[0] <= cutoff:
            hits.popleft()
        if len(hits) >= limit:
            return max(0.0, _WINDOW_SECONDS - (now - hits[0]))
        hits.append(now)
        return None


limiter = RateLimiter(TIER_LIMITS)
