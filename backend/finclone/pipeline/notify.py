"""Alerting for the validation review queue (QA review Aug 2026, Analytics #1).

The queue was doing its job — holding disputed figures instead of publishing
them — but nothing told anyone an item had arrived. A held figure nobody looks
at is indistinguishable from a figure we never checked, so items could sit
open indefinitely (the AAPL long-term-debt flags sat across three fiscal years).

Delivery is deliberately pluggable and deliberately non-fatal:

* `FINCLONE_ALERT_WEBHOOK` — any Slack/Teams-compatible incoming webhook. Unset
  in dev, so local runs just log.
* stdout always, so the sweep's own log is a complete record even with no
  webhook configured.

An alert failure must never take down a crossref sweep: the sweep's job is to
find discrepancies, and losing 400 companies of validation because a webhook
returned 500 would be a strictly worse outcome than a missed notification.
"""

import os

import httpx

# Where to send queue alerts. Slack/Teams incoming-webhook shape: {"text": ...}.
ALERT_WEBHOOK = os.environ.get("FINCLONE_ALERT_WEBHOOK", "").strip()

# Below this variance a new flag is logged but not pushed. The queue flags at
# 1% by design (see CROSSREF_VARIANCE_THRESHOLD); paging a human for a 1.2%
# rounding difference is how alerting gets muted wholesale, which costs more
# than the alerts are worth. Raise it if the channel still gets noisy.
ALERT_MIN_VARIANCE = float(os.environ.get("FINCLONE_ALERT_MIN_VARIANCE", "0.05"))

# Cap on flags named individually in one message. The rest are counted, not
# listed — a 200-line alert is scrolled past, not read.
_MAX_LISTED = 8

# Where a human goes to act on the alert.
WEB_BASE = os.environ.get("FINCLONE_WEB_BASE", "http://localhost:3000").rstrip("/")


class NewFlag:
    """One newly-opened queue item, in the terms an analyst reviews it in."""

    __slots__ = ("ticker", "concept", "fiscal_year", "our_value",
                 "reference_value", "variance")

    def __init__(self, ticker: str, concept: str, fiscal_year: int,
                 our_value: float, reference_value: float, variance: float):
        self.ticker = ticker
        self.concept = concept
        self.fiscal_year = fiscal_year
        self.our_value = our_value
        self.reference_value = reference_value
        self.variance = variance

    def line(self) -> str:
        return (f"{self.ticker} {self.concept} FY{self.fiscal_year}: "
                f"ours {self.our_value:,.0f} vs reference "
                f"{self.reference_value:,.0f} ({self.variance:.1%})")


def format_message(flags: list[NewFlag]) -> str:
    """The alert body. Kept separate from delivery so it is testable without
    a webhook and identical across every transport."""
    tickers = sorted({f.ticker for f in flags})
    who = tickers[0] if len(tickers) == 1 else f"{len(tickers)} companies"
    header = (f"Validation review queue: {len(flags)} new item"
              f"{'s' if len(flags) != 1 else ''} for {who}")

    ranked = sorted(flags, key=lambda f: -f.variance)
    body = "\n".join(f"  • {f.line()}" for f in ranked[:_MAX_LISTED])
    if len(ranked) > _MAX_LISTED:
        body += f"\n  … and {len(ranked) - _MAX_LISTED} more"

    link = (f"{WEB_BASE}/company/{tickers[0]}" if len(tickers) == 1
            else f"{WEB_BASE}/dashboard")
    return f"{header}\n{body}\n\nReview: {link}"


def notify_new_flags(flags: list[NewFlag]) -> bool:
    """Announce newly-opened queue items. Returns True if a push was delivered.

    Never raises: callers are mid-sweep and a failed alert must not cost them
    the validation work they just did.
    """
    if not flags:
        return False

    pushable = [f for f in flags if f.variance >= ALERT_MIN_VARIANCE]
    message = format_message(flags)
    print(message)

    if not pushable:
        print(f"  (not pushed: all below the {ALERT_MIN_VARIANCE:.0%} alert threshold)")
        return False
    if not ALERT_WEBHOOK:
        print("  (not pushed: FINCLONE_ALERT_WEBHOOK is unset)")
        return False

    try:
        resp = httpx.post(ALERT_WEBHOOK, json={"text": format_message(pushable)},
                          timeout=10.0)
        resp.raise_for_status()
        return True
    except Exception as e:  # noqa: BLE001 — see docstring; alerting is best-effort
        print(f"  (alert delivery failed: {type(e).__name__}: {str(e)[:120]})")
        return False
