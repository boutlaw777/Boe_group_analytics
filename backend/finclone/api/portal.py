"""Self-serve developer portal (PDR Module 5 extension).

Signup/login issue an opaque bearer token (one active session per account,
rotated on each login). Portal accounts mint their own free-tier keys —
capped per account so fresh keys can't be farmed to dodge rate limits.
Higher tiers stay admin-provisioned.
"""

import re
from datetime import date, timedelta

from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from finclone.api import auth as api_auth
from finclone.db import get_session
from finclone.models import ApiKey, ApiKeyUsage, DevAccount

router = APIRouter()

SESSION_DAYS = 30
MAX_ACTIVE_KEYS = 2  # per account, free tier — contact us for more/higher tiers

_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def _session() -> Session:
    session = get_session()
    try:
        yield session
    finally:
        session.close()


class Credentials(BaseModel):
    email: str
    password: str


def _normalize_email(email: str) -> str:
    email = email.strip().lower()
    if not _EMAIL_RE.match(email):
        raise HTTPException(422, "That doesn't look like a valid email address")
    return email


def _issue_token(session: Session, account: DevAccount) -> str:
    token = api_auth.generate_session_token()
    account.token_hash = api_auth.hash_key(token)
    account.token_expires = date.today() + timedelta(days=SESSION_DAYS)
    session.commit()
    return token


def current_account(
    authorization: str | None = Header(None),
    session: Session = Depends(_session),
) -> DevAccount:
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(401, "Missing bearer token — log in first")
    token_hash = api_auth.hash_key(authorization[len("Bearer "):].strip())
    account = session.scalar(select(DevAccount).where(DevAccount.token_hash == token_hash))
    if account is None or (account.token_expires and account.token_expires < date.today()):
        raise HTTPException(401, "Session expired — log in again")
    return account


@router.post("/auth/signup", status_code=201)
def signup(body: Credentials, session: Session = Depends(_session)) -> dict:
    email = _normalize_email(body.email)
    if len(body.password) < 8:
        raise HTTPException(422, "Password must be at least 8 characters")
    if session.scalar(select(DevAccount).where(DevAccount.email == email)):
        raise HTTPException(409, "An account with this email already exists — log in instead")
    account = DevAccount(email=email, password_hash=api_auth.hash_password(body.password),
                         created=date.today())
    session.add(account)
    session.commit()
    return {"email": email, "token": _issue_token(session, account)}


@router.post("/auth/login")
def login(body: Credentials, session: Session = Depends(_session)) -> dict:
    email = _normalize_email(body.email)
    account = session.scalar(select(DevAccount).where(DevAccount.email == email))
    if account is None or not api_auth.verify_password(body.password, account.password_hash):
        raise HTTPException(401, "Wrong email or password")
    return {"email": email, "token": _issue_token(session, account)}


@router.get("/me")
def me(account: DevAccount = Depends(current_account)) -> dict:
    return {"email": account.email, "created": account.created.isoformat()}


def _key_json(k: ApiKey) -> dict:
    return {"id": k.id, "name": k.name, "prefix": k.prefix, "tier": k.tier,
            "active": k.active, "requests": k.requests, "created": k.created.isoformat()}


@router.get("/me/keys")
def my_keys(account: DevAccount = Depends(current_account),
            session: Session = Depends(_session)) -> list[dict]:
    rows = session.scalars(select(ApiKey).where(ApiKey.account_id == account.id)
                           .order_by(ApiKey.id))
    return [_key_json(k) for k in rows]


class KeyCreate(BaseModel):
    name: str = "default"


@router.post("/me/keys", status_code=201)
def create_my_key(body: KeyCreate, account: DevAccount = Depends(current_account),
                  session: Session = Depends(_session)) -> dict:
    """Mint a free-tier key. The raw key appears in this response only."""
    active = session.scalar(
        select(func.count()).select_from(ApiKey)
        .where(ApiKey.account_id == account.id, ApiKey.active.is_(True)))
    if active >= MAX_ACTIVE_KEYS:
        raise HTTPException(
            409, f"Limit of {MAX_ACTIVE_KEYS} active keys per account — revoke one "
                 "first, or contact us for a higher tier")
    raw = api_auth.generate_key()
    key = ApiKey(name=body.name.strip()[:128] or "default",
                 key_hash=api_auth.hash_key(raw), prefix=raw[:12], tier="free",
                 created=date.today(), account_id=account.id)
    session.add(key)
    session.commit()
    return {**_key_json(key), "api_key": raw}


@router.delete("/me/keys/{key_id}")
def revoke_my_key(key_id: int, account: DevAccount = Depends(current_account),
                  session: Session = Depends(_session)) -> dict:
    key = session.get(ApiKey, key_id)
    if key is None or key.account_id != account.id:
        raise HTTPException(404, f"No key {key_id} on this account")
    key.active = False
    session.commit()
    return _key_json(key)


@router.get("/me/usage")
def my_usage(days: int = 30, account: DevAccount = Depends(current_account),
             session: Session = Depends(_session)) -> list[dict]:
    """Requests per day across all of the account's keys, zero-filled."""
    days = max(1, min(days, 90))
    since = date.today() - timedelta(days=days - 1)
    rows = session.execute(
        select(ApiKeyUsage.day, func.sum(ApiKeyUsage.count))
        .join(ApiKey, ApiKey.id == ApiKeyUsage.key_id)
        .where(ApiKey.account_id == account.id, ApiKeyUsage.day >= since)
        .group_by(ApiKeyUsage.day)
    ).all()
    by_day = {d: int(c) for d, c in rows}
    return [{"date": (since + timedelta(days=i)).isoformat(),
             "requests": by_day.get(since + timedelta(days=i), 0)}
            for i in range(days)]
