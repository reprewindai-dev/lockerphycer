import os
import uuid


def _set_test_env():
    os.environ.setdefault("SECRET_KEY", "test-secret-key-test-secret-key-test-1234")
    os.environ.setdefault("ENVIRONMENT", "development")
    os.environ.setdefault("DEBUG", "true")
    os.environ["DATABASE_URL"] = "sqlite+aiosqlite:///./test_lockerphycer.db"


def test_password_reset_token_is_single_use_and_revokes_sessions():
    _set_test_env()

    from fastapi.testclient import TestClient

    from apps.api.main import app
    from core.security.auth import create_email_verification_token, create_password_reset_token
    from core.database.database import SessionLocal
    from db.models import User
    from sqlalchemy import select
    import asyncio
    import hashlib

    email = f"recovery-{uuid.uuid4()}@example.com"
    original_password = "CorrectHorseBatteryStaple1"
    replacement_password = "DifferentHorseBatteryStaple2"

    with TestClient(app) as client:
        registered = client.post(
            "/api/v1/auth/register",
            json={
                "email": email,
                "username": f"recovery-{uuid.uuid4().hex[:8]}",
                "full_name": "Recovery User",
                "password": original_password,
            },
        )
        assert registered.status_code == 201

        verified = client.post(
            "/api/v1/auth/email-verification/confirm",
            json={"token": create_email_verification_token(email)},
        )
        assert verified.status_code == 200

        login = client.post(
            "/api/v1/auth/login",
            json={"email": email, "password": original_password},
        )
        assert login.status_code == 200
        access = login.json()["access_token"]

        async def reset_token():
            async with SessionLocal() as session:
                user = (await session.execute(select(User).where(User.email == email))).scalars().one()
                version = hashlib.sha256(user.hashed_password.encode("utf-8")).hexdigest()
                return create_password_reset_token(email, version)

        token = asyncio.run(reset_token())
        reset = client.post(
            "/api/v1/auth/password-reset/confirm",
            json={"token": token, "new_password": replacement_password},
        )
        assert reset.status_code == 200

        revoked = client.get(
            "/api/v1/auth/me",
            headers={"Authorization": f"Bearer {access}"},
        )
        assert revoked.status_code == 401

        replay = client.post(
            "/api/v1/auth/password-reset/confirm",
            json={"token": token, "new_password": original_password},
        )
        assert replay.status_code == 401

        old_login = client.post(
            "/api/v1/auth/login",
            json={"email": email, "password": original_password},
        )
        assert old_login.status_code == 401

        new_login = client.post(
            "/api/v1/auth/login",
            json={"email": email, "password": replacement_password},
        )
        assert new_login.status_code == 200
