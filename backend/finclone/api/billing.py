"""Stripe billing: self-serve tier upgrades (PDR Module 5).

Replaces the previous admin-provisioned pro/enterprise keys — a dev account
upgrades itself through Stripe Checkout, and webhooks flip the account's API
keys to the paid tier (and back to free when the subscription lapses).

Design notes:
- Stripe is the source of truth; the `subscriptions` table caches current
  state so tier checks never call Stripe. Webhooks keep the cache in sync.
- Everything is guarded on STRIPE_SECRET_KEY. When it's unset (before Stripe
  is wired up), the endpoints return 503 "billing not configured" and the rest
  of the API is unaffected — the same graceful-degradation pattern the codebase
  uses for optional providers (Gemini KPI, SimFin, Supabase).
- The webhook is unauthenticated by design; Stripe's signature (verified with
  STRIPE_WEBHOOK_SECRET) is its auth. Never trust an unverified webhook body.
"""

from datetime import date, datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from finclone import config
from finclone.api.portal import current_account
from finclone.db import get_session
from finclone.models import ApiKey, DevAccount, Subscription

try:  # Stripe is an optional dependency until billing is configured.
    import stripe
except ImportError:  # pragma: no cover - exercised only before `pip install`
    stripe = None

router = APIRouter(prefix="/billing")


def _session() -> Session:
    session = get_session()
    try:
        yield session
    finally:
        session.close()


def _billing_ready() -> bool:
    return stripe is not None and bool(config.STRIPE_SECRET_KEY)


def _require_billing() -> None:
    """Guard every live endpoint so an unconfigured deployment fails clearly."""
    if stripe is None:
        raise HTTPException(503, "Billing unavailable — the 'stripe' package is not installed")
    if not config.STRIPE_SECRET_KEY:
        raise HTTPException(503, "Billing not configured — STRIPE_SECRET_KEY is unset")
    stripe.api_key = config.STRIPE_SECRET_KEY


def _get_or_create_sub(session: Session, account_id: int) -> Subscription:
    sub = session.get(Subscription, account_id)
    if sub is None:
        sub = Subscription(account_id=account_id, tier="free",
                           status="inactive", updated=date.today())
        session.add(sub)
    return sub


def _sync_account_keys(session: Session, account_id: int, tier: str) -> None:
    """Set every active key on the account to `tier` — this is what actually
    changes the rate limit the customer experiences."""
    keys = session.scalars(
        select(ApiKey).where(ApiKey.account_id == account_id)).all()
    for key in keys:
        key.tier = tier


def _period_end(unix_ts: int | None) -> date | None:
    if not unix_ts:
        return None
    return datetime.fromtimestamp(unix_ts, tz=timezone.utc).date()


# --- Customer-facing endpoints (authenticated) --------------------------------

class CheckoutIn(BaseModel):
    tier: str  # "pro" or "enterprise"


@router.get("/subscription")
def my_subscription(account: DevAccount = Depends(current_account),
                    session: Session = Depends(_session)) -> dict:
    """Current plan for the logged-in account (free when never subscribed)."""
    sub = session.get(Subscription, account.id)
    if sub is None:
        return {"tier": "free", "status": "inactive", "current_period_end": None}
    return {"tier": sub.tier, "status": sub.status,
            "current_period_end": sub.current_period_end.isoformat()
            if sub.current_period_end else None}


@router.post("/checkout")
def create_checkout(body: CheckoutIn,
                    account: DevAccount = Depends(current_account),
                    session: Session = Depends(_session)) -> dict:
    """Start a Stripe Checkout for a paid tier; returns the hosted checkout URL.

    We pass client_reference_id=account.id so the webhook can attribute the
    resulting subscription back to this account even before we know the Stripe
    customer id."""
    _require_billing()
    price_id = config.STRIPE_PRICE_BY_TIER.get(body.tier)
    if not price_id:
        raise HTTPException(
            422, f"No Stripe price configured for tier '{body.tier}' — "
            f"set STRIPE_PRICE_{body.tier.upper()} (available: "
            f"{sorted(config.STRIPE_PRICE_BY_TIER) or 'none'})")

    sub = _get_or_create_sub(session, account.id)
    customer_id = sub.stripe_customer_id
    if not customer_id:
        customer = stripe.Customer.create(
            email=account.email, metadata={"account_id": account.id})
        customer_id = customer["id"]
        sub.stripe_customer_id = customer_id
    session.commit()

    checkout = stripe.checkout.Session.create(
        mode="subscription",
        customer=customer_id,
        client_reference_id=str(account.id),
        line_items=[{"price": price_id, "quantity": 1}],
        success_url=config.BILLING_SUCCESS_URL,
        cancel_url=config.BILLING_CANCEL_URL,
    )
    return {"checkout_url": checkout["url"]}


@router.post("/portal")
def billing_portal(account: DevAccount = Depends(current_account),
                   session: Session = Depends(_session)) -> dict:
    """Stripe-hosted billing portal so the customer can update payment method,
    view invoices, or cancel."""
    _require_billing()
    sub = session.get(Subscription, account.id)
    if sub is None or not sub.stripe_customer_id:
        raise HTTPException(404, "No billing account yet — subscribe first")
    portal = stripe.billing_portal.Session.create(
        customer=sub.stripe_customer_id, return_url=config.BILLING_SUCCESS_URL)
    return {"portal_url": portal["url"]}


# --- Stripe webhook (unauthenticated; verified by signature) ------------------

def _apply_subscription(session: Session, account_id: int,
                        stripe_sub: dict) -> None:
    """Upsert our cached Subscription from a Stripe subscription object and sync
    the account's key tiers."""
    items = stripe_sub.get("items", {}).get("data", [])
    price_id = items[0]["price"]["id"] if items else None
    status = stripe_sub.get("status", "inactive")
    # Active/trialing → the paid tier; anything else → free.
    tier = config.TIER_BY_STRIPE_PRICE.get(price_id, "free")
    effective_tier = tier if status in ("active", "trialing") else "free"

    sub = _get_or_create_sub(session, account_id)
    sub.stripe_subscription_id = stripe_sub.get("id")
    sub.stripe_customer_id = stripe_sub.get("customer") or sub.stripe_customer_id
    sub.tier = effective_tier
    sub.status = status
    sub.current_period_end = _period_end(stripe_sub.get("current_period_end"))
    sub.updated = date.today()
    _sync_account_keys(session, account_id, effective_tier)
    session.commit()


def _account_id_for_customer(session: Session, customer_id: str | None) -> int | None:
    if not customer_id:
        return None
    sub = session.scalar(
        select(Subscription).where(Subscription.stripe_customer_id == customer_id))
    return sub.account_id if sub else None


@router.post("/webhook")
async def stripe_webhook(request: Request,
                         session: Session = Depends(_session)) -> dict:
    """Handle Stripe subscription lifecycle events. Signature-verified with
    STRIPE_WEBHOOK_SECRET — the raw body must be used for verification, so we
    read it directly rather than via a parsed model."""
    _require_billing()
    if not config.STRIPE_WEBHOOK_SECRET:
        raise HTTPException(503, "Webhook not configured — STRIPE_WEBHOOK_SECRET is unset")

    payload = await request.body()
    sig = request.headers.get("stripe-signature", "")
    try:
        event = stripe.Webhook.construct_event(
            payload, sig, config.STRIPE_WEBHOOK_SECRET)
    except (ValueError, stripe.error.SignatureVerificationError):
        # Bad payload or forged signature — reject.
        raise HTTPException(400, "Invalid Stripe signature")

    kind = event["type"]
    obj = event["data"]["object"]

    if kind == "checkout.session.completed":
        account_id = obj.get("client_reference_id")
        sub_id = obj.get("subscription")
        if account_id and sub_id:
            stripe_sub = stripe.Subscription.retrieve(sub_id)
            _apply_subscription(session, int(account_id), stripe_sub)

    elif kind in ("customer.subscription.updated", "customer.subscription.created"):
        account_id = _account_id_for_customer(session, obj.get("customer"))
        if account_id:
            _apply_subscription(session, account_id, obj)

    elif kind == "customer.subscription.deleted":
        account_id = _account_id_for_customer(session, obj.get("customer"))
        if account_id:
            sub = _get_or_create_sub(session, account_id)
            sub.tier = "free"
            sub.status = "canceled"
            sub.updated = date.today()
            _sync_account_keys(session, account_id, "free")
            session.commit()

    # Unhandled event types are acknowledged so Stripe stops retrying.
    return {"received": True}
