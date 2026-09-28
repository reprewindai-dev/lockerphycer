import os
import uuid


def _set_test_env():
    os.environ.setdefault("SECRET_KEY", "test-secret-key-test-secret-key-test-1234")
    os.environ.setdefault("ENVIRONMENT", "development")
    os.environ.setdefault("DEBUG", "true")
    os.environ["DATABASE_URL"] = "sqlite+aiosqlite:///./test_lockerphycer.db"


def test_registration_persists_inactive_identity_when_delivery_is_down(monkeypatch):
    _set_test_env()

    from fastapi.testclient import TestClient
    from apps.api.main import app
    import apps.api.routers.auth as auth_router
    from core.database.database import SessionLocal
    from db.models import User
    from sqlalchemy import select
    import asyncio

    email = f"delivery-failure-{uuid.uuid4().hex}@example.com"
    monkeypatch.setattr(auth_router, "_send_verification", lambda user: _false_async())

    with TestClient(app) as client:
        response = client.post(
            "/api/v1/auth/register",
            json={
                "email": email,
                "username": f"delivery-{uuid.uuid4().hex[:8]}",
                "full_name": "Delivery Failure",
                "password": "CorrectHorseBatteryStaple1",
            },
        )

        assert response.status_code == 201
        denied = client.post('/api/v1/auth/login', json={
            'email': email, 'password': 'CorrectHorseBatteryStaple1'})
        assert denied.status_code == 403

    async def user_exists():
        async with SessionLocal() as session:
            result = await session.execute(select(User).where(User.email == email))
            user = result.scalars().one()
            from db.models import UserStatus
            from apps.email.outbox import IdentityEmailOutbox
            queued = (await session.execute(select(IdentityEmailOutbox).where(
                IdentityEmailOutbox.user_id == user.id))).scalars().one()
            return user.status == UserStatus.INACTIVE and queued.status == 'QUEUED'

    assert asyncio.run(user_exists()) is True


async def _false_async():
    return False
