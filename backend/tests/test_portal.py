from datetime import date, timedelta

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from finclone.api import auth as api_auth
from finclone.api.portal import (Credentials, KeyCreate, MAX_ACTIVE_KEYS, create_my_key,
                                 current_account, login, my_keys, my_usage, revoke_my_key,
                                 signup)
from finclone.db import Base
from finclone.models import ApiKey, ApiKeyUsage, DevAccount


@pytest.fixture()
def session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with sessionmaker(bind=engine)() as s:
        yield s


def _account(session, email="dev@example.com", password="hunter2secret"):
    out = signup(Credentials(email=email, password=password), session)
    return session.query(DevAccount).filter_by(email=out["email"]).one(), out["token"]


def test_password_hashing_roundtrip():
    stored = api_auth.hash_password("correct horse")
    assert api_auth.verify_password("correct horse", stored)
    assert not api_auth.verify_password("wrong", stored)
    assert not api_auth.verify_password("anything", "malformed-hash")


def test_signup_and_login(session):
    out = signup(Credentials(email="Dev@Example.COM ", password="longenough"), session)
    assert out["email"] == "dev@example.com"  # normalized
    assert out["token"].startswith("boes_")

    ok = login(Credentials(email="dev@example.com", password="longenough"), session)
    assert ok["token"].startswith("boes_")

    with pytest.raises(HTTPException) as e:
        login(Credentials(email="dev@example.com", password="wrongpass"), session)
    assert e.value.status_code == 401


def test_signup_rejects_dupes_and_weak_input(session):
    signup(Credentials(email="dev@example.com", password="longenough"), session)
    with pytest.raises(HTTPException) as e:
        signup(Credentials(email="dev@example.com", password="longenough"), session)
    assert e.value.status_code == 409
    with pytest.raises(HTTPException) as e:
        signup(Credentials(email="notanemail", password="longenough"), session)
    assert e.value.status_code == 422
    with pytest.raises(HTTPException) as e:
        signup(Credentials(email="a@b.co", password="short"), session)
    assert e.value.status_code == 422


def test_bearer_session_and_expiry(session):
    account, token = _account(session)
    assert current_account(f"Bearer {token}", session).id == account.id

    with pytest.raises(HTTPException):
        current_account("Bearer boes_not_a_real_token", session)
    with pytest.raises(HTTPException):
        current_account(None, session)

    account.token_expires = date.today() - timedelta(days=1)
    session.commit()
    with pytest.raises(HTTPException) as e:
        current_account(f"Bearer {token}", session)
    assert e.value.status_code == 401


def test_key_lifecycle_and_cap(session):
    account, _ = _account(session)
    first = create_my_key(KeyCreate(name="ci"), account, session)
    assert first["api_key"].startswith("boe_") and first["tier"] == "free"

    for _ in range(MAX_ACTIVE_KEYS - 1):
        create_my_key(KeyCreate(), account, session)
    with pytest.raises(HTTPException) as e:
        create_my_key(KeyCreate(), account, session)
    assert e.value.status_code == 409

    revoked = revoke_my_key(first["id"], account, session)
    assert revoked["active"] is False
    create_my_key(KeyCreate(), account, session)  # slot freed

    other, _ = _account(session, email="other@example.com")
    with pytest.raises(HTTPException) as e:
        revoke_my_key(first["id"], other, session)
    assert e.value.status_code == 404


def test_usage_aggregates_and_zero_fills(session):
    account, _ = _account(session)
    k1 = create_my_key(KeyCreate(name="a"), account, session)
    k2 = create_my_key(KeyCreate(name="b"), account, session)
    today = date.today()
    session.add_all([
        ApiKeyUsage(key_id=k1["id"], day=today, count=3),
        ApiKeyUsage(key_id=k2["id"], day=today, count=2),
        ApiKeyUsage(key_id=k1["id"], day=today - timedelta(days=2), count=7),
    ])
    # another account's traffic must not leak in
    stranger, _ = _account(session, email="x@example.com")
    ks = create_my_key(KeyCreate(), stranger, session)
    session.add(ApiKeyUsage(key_id=ks["id"], day=today, count=99))
    session.commit()

    series = my_usage(7, account, session)
    assert len(series) == 7
    assert series[-1] == {"date": today.isoformat(), "requests": 5}
    assert series[-3]["requests"] == 7
    assert all(p["requests"] == 0 for p in series[:-3])
