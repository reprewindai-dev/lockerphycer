import asyncio
import os
import uuid


def _set_test_env():
    os.environ.setdefault("SECRET_KEY", "test-secret-key-test-secret-key-test-1234")
    os.environ.setdefault("ENVIRONMENT", "development")
    os.environ.setdefault("DEBUG", "true")
    os.environ["DATABASE_URL"] = "sqlite+aiosqlite:///./test_lockerphycer.db"


async def _true_async():
    return True


def _register(client, email, **extra):
    return client.post(
        "/api/v1/auth/register",
        headers={"user-agent": "agreement-test-agent"},
        json={
            "email": email,
            "username": f"agree-{uuid.uuid4().hex[:8]}",
            "full_name": "Agreement Test",
            "password": f"Pw-{uuid.uuid4().hex}",  # generated: no credential-shaped literal in the repo
            **extra,
        },
    )


def _rows_and_user(email):
    from sqlalchemy import select
    from core.database.database import SessionLocal
    from db.models import AgreementAcceptance, User

    async def load():
        async with SessionLocal() as session:
            user = (await session.execute(select(User).where(User.email == email))).scalars().first()
            if user is None:
                return None, []
            rows = (await session.execute(
                select(AgreementAcceptance).where(AgreementAcceptance.user_id == user.id))).scalars().all()
            return user, rows

    return asyncio.run(load())


def test_signup_records_every_current_agreement_with_the_account(monkeypatch):
    _set_test_env()
    from fastapi.testclient import TestClient
    from apps.api.main import app
    import apps.api.routers.auth as auth_router
    from core.agreements import CURRENT_AGREEMENTS

    monkeypatch.setattr(auth_router, "_send_verification", lambda user: _true_async())
    email = f"agree-all-{uuid.uuid4().hex}@example.com"
    with TestClient(app) as client:
        response = _register(client, email, accepted_agreements=list(CURRENT_AGREEMENTS))
    assert response.status_code == 201

    user, rows = _rows_and_user(email)
    assert user is not None
    # One row per current document, at the server's version (the client sends no versions).
    assert {(r.document_type, r.document_version) for r in rows} == set(CURRENT_AGREEMENTS.items())
    assert all(r.source == "signup_form" for r in rows)
    assert all(r.user_agent == "agreement-test-agent" for r in rows)


def test_incomplete_or_unknown_agreements_create_no_account(monkeypatch):
    _set_test_env()
    from fastapi.testclient import TestClient
    from apps.api.main import app
    import apps.api.routers.auth as auth_router
    from core.agreements import CURRENT_AGREEMENTS

    monkeypatch.setattr(auth_router, "_send_verification", lambda user: _true_async())
    missing_one = list(CURRENT_AGREEMENTS)[1:]
    with TestClient(app) as client:
        email_missing = f"agree-missing-{uuid.uuid4().hex}@example.com"
        refused = _register(client, email_missing, accepted_agreements=missing_one)
        email_unknown = f"agree-unknown-{uuid.uuid4().hex}@example.com"
        unknown = _register(client, email_unknown, accepted_agreements=[*CURRENT_AGREEMENTS, "made_up"])

    assert refused.status_code == 422
    message = refused.json()["error"]["message"]
    assert message.startswith("AGREEMENTS_INCOMPLETE")
    assert f"missing: {list(CURRENT_AGREEMENTS)[0]}" in message
    assert unknown.status_code == 422
    assert "unknown: made_up" in unknown.json()["error"]["message"]
    assert _rows_and_user(email_missing) == (None, [])
    assert _rows_and_user(email_unknown) == (None, [])


def test_signup_without_the_field_still_works_and_records_nothing(monkeypatch):
    _set_test_env()
    from fastapi.testclient import TestClient
    from apps.api.main import app
    import apps.api.routers.auth as auth_router

    monkeypatch.setattr(auth_router, "_send_verification", lambda user: _true_async())
    email = f"agree-none-{uuid.uuid4().hex}@example.com"
    with TestClient(app) as client:
        response = _register(client, email)
    assert response.status_code == 201
    user, rows = _rows_and_user(email)
    assert user is not None and rows == []
