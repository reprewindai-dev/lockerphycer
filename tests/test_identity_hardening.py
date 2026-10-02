"""Login-time MFA, per-account security events, and routes that must not be
reachable without a session."""
import asyncio
import os
import uuid


def _set_test_env():
    os.environ.setdefault("SECRET_KEY", "test-secret-key-test-secret-key-test-1234")
    os.environ.setdefault("ENVIRONMENT", "development")
    os.environ.setdefault("DEBUG", "true")
    os.environ["DATABASE_URL"] = "sqlite+aiosqlite:///./test_lockerphycer.db"


def _session(client, *, admin: bool = False):
    from test_workspace_onboarding import _seed_user

    _, token, _ = _seed_user(admin=admin)
    headers = {"Authorization": f"Bearer {token}"}
    me = client.get("/api/v1/auth/me", headers=headers)
    assert me.status_code == 200
    return me.json(), headers


def _seed_mfa_user():
    import pyotp

    from core.database.database import Base, SessionLocal, engine
    from core.security.auth import get_password_hash
    from db.models import User, UserRole, UserStatus

    email = f"mfa-{uuid.uuid4().hex}@example.com"
    secret = pyotp.random_base32()

    async def seed():
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        async with SessionLocal() as session:
            session.add(
                User(
                    email=email,
                    username=f"mfa-{uuid.uuid4().hex[:10]}",
                    hashed_password=get_password_hash("CorrectHorseBatteryStaple1"),
                    role=UserRole.USER,
                    status=UserStatus.ACTIVE,
                    mfa_enabled=True,
                    mfa_secret=secret,
                )
            )
            await session.commit()

    asyncio.run(seed())
    return email, secret


def test_password_alone_does_not_sign_in_an_mfa_account():
    _set_test_env()
    import pyotp
    from fastapi.testclient import TestClient
    from apps.api.main import app

    email, secret = _seed_mfa_user()
    credentials = {"email": email, "password": "CorrectHorseBatteryStaple1"}

    with TestClient(app) as client:
        no_code = client.post("/api/v1/auth/login", json=credentials)
        assert no_code.status_code == 401
        assert "access_token" not in no_code.text
        assert "MFA code required" in no_code.text

        wrong_code = client.post("/api/v1/auth/login", json={**credentials, "mfa_code": "000000"})
        assert wrong_code.status_code == 401
        assert "access_token" not in wrong_code.text

        # A wrong password must not reveal that the account has MFA.
        wrong_password = client.post("/api/v1/auth/login", json={"email": email, "password": "WrongHorseBatteryStaple9"})
        assert wrong_password.status_code == 401
        assert "MFA" not in wrong_password.text

        good = client.post("/api/v1/auth/login", json={**credentials, "mfa_code": pyotp.TOTP(secret).now()})
        assert good.status_code == 200
        token = good.json()["access_token"]
        assert client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"}).status_code == 200


def test_security_events_are_scoped_to_the_account():
    _set_test_env()
    from fastapi.testclient import TestClient
    from apps.api.main import app

    event = {"event_type": "login_anomaly", "security_level": "high", "description": "scoped event"}

    with TestClient(app) as client:
        alice, alice_headers = _session(client)
        bob, bob_headers = _session(client)
        _, staff_headers = _session(client, admin=True)

        created = client.post("/api/v1/security/events", headers=alice_headers, json={**event, "user_id": bob["id"]})
        assert created.status_code == 200
        event_id = created.json()["id"]
        # A non-staff account cannot record an event against someone else.
        assert created.json()["user_id"] == alice["id"]

        assert event_id in [row["id"] for row in client.get("/api/v1/security/events", headers=alice_headers).json()]
        assert event_id not in [row["id"] for row in client.get("/api/v1/security/events", headers=bob_headers).json()]
        assert client.get(f"/api/v1/security/events/{event_id}", headers=bob_headers).status_code == 404
        assert client.put(f"/api/v1/security/events/{event_id}/resolve", headers=bob_headers, params={"resolution": "x"}).status_code == 403
        assert client.put(f"/api/v1/security/events/{event_id}/resolve", headers=alice_headers, params={"resolution": "x"}).status_code == 403
        assert client.get("/api/v1/security/threats/stats", headers=bob_headers).json()["total_threats"] == 0

        assert event_id in [row["id"] for row in client.get("/api/v1/security/events", headers=staff_headers, params={"limit": 1000}).json()]
        assert client.put(f"/api/v1/security/events/{event_id}/resolve", headers=staff_headers, params={"resolution": "handled"}).status_code == 200


def test_routes_that_need_a_session_refuse_anonymous_callers():
    _set_test_env()
    from fastapi.testclient import TestClient
    from apps.api.main import app

    with TestClient(app) as client:
        for method, path in [
            ("get", "/api/v1/gpc/plans"),
            ("get", "/api/v1/gpc/stats"),
            ("get", "/api/v1/feedback/"),
            ("get", "/api/v1/marketplace/listings"),
            ("get", "/api/v1/security/events"),
            ("get", "/api/v1/users/"),
        ]:
            response = getattr(client, method)(path)
            assert response.status_code in (401, 403), (path, response.status_code)

        _, headers = _session(client)
        assert client.put("/api/v1/marketplace/listings/anything/publish", headers=headers).status_code == 403
        assert client.post("/api/v1/gpc/plans/anything/approve", headers=headers).status_code == 403


def test_external_engine_proxy_is_gone():
    _set_test_env()
    from fastapi.testclient import TestClient
    from apps.api.main import app

    with TestClient(app) as client:
        for path in ("/gpc-engine/", "/gpc-engine/api/anything"):
            response = client.get(path, headers={"Authorization": "Bearer should-never-leave"}, follow_redirects=False)
            assert response.status_code == 404, (path, response.status_code)
