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


def test_rate_limit_bucket_cannot_be_chosen_with_forwarded_headers():
    _set_test_env()
    from starlette.requests import Request

    from core.security.middleware import trusted_client_ip

    def request(headers: dict, peer: str = "10.0.0.7") -> Request:
        raw = [(k.lower().encode(), v.encode()) for k, v in headers.items()]
        return Request({"type": "http", "headers": raw, "client": (peer, 5555), "method": "GET", "path": "/"})

    # Caller-controlled headers never change the address.
    assert trusted_client_ip(request({"X-Forwarded-For": "1.2.3.4", "X-Real-IP": "5.6.7.8"})) == "10.0.0.7"
    # The Cloudflare edge header does, when it is a real address.
    assert trusted_client_ip(request({"CF-Connecting-IP": "203.0.113.9", "X-Forwarded-For": "1.2.3.4"})) == "203.0.113.9"
    assert trusted_client_ip(request({"CF-Connecting-IP": "not-an-ip"})) == "10.0.0.7"


def test_machine_token_exchange_identifies_the_machine_and_always_expires():
    _set_test_env()
    from fastapi.testclient import TestClient
    import base64
    import json

    from apps.api.main import app
    from test_workspace_onboarding import _seed_user

    _, token, workspace_id = _seed_user(workspace=True)
    headers = {"Authorization": f"Bearer {token}"}

    with TestClient(app) as client:
        for days in (0, -5, 100000):
            rejected = client.post("/api/v1/machine-tokens", headers=headers, json={"name": "agent", "workspace_id": workspace_id, "expires_in_days": days})
            assert rejected.status_code == 422, days

        created = client.post("/api/v1/machine-tokens", headers=headers, json={"name": "agent-one", "workspace_id": workspace_id})
        assert created.status_code == 200, created.text
        machine = created.json()

        exchanged = client.post("/api/v1/machine-tokens/exchange", headers={"Authorization": f"Bearer {machine['secret']}"})
        assert exchanged.status_code == 200
        payload = exchanged.json()["access_token"].split(".")[1]
        claims = json.loads(base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4)))
        assert claims["principal_type"] == "machine"
        assert claims["machine_token_id"] == machine["id"]
        assert claims["act"]["sub"] == f"machine:{machine['id']}"
        assert claims["workspace_id"] == workspace_id

        assert client.delete(f"/api/v1/machine-tokens/{machine['id']}", headers=headers).status_code == 200
        revoked = client.post("/api/v1/machine-tokens/exchange", headers={"Authorization": f"Bearer {machine['secret']}"})
        assert revoked.status_code == 401


def test_mfa_setup_endpoints_work_over_http():
    """The service functions were tested, the routes were not: setup failed in the
    built image because the QR image library was never installed."""
    _set_test_env()
    import pyotp
    from fastapi.testclient import TestClient
    from apps.api.main import app

    with TestClient(app) as client:
        _, headers = _session(client)
        setup = client.post("/api/v1/auth/mfa/setup", headers=headers)
        assert setup.status_code == 200, setup.text
        secret = setup.json()["secret"]
        assert setup.json()["provisioning_uri"].startswith("otpauth://totp/")

        qr = client.get("/api/v1/auth/mfa/setup/qr", headers=headers)
        assert qr.status_code == 200 and qr.content[:8] == b"\x89PNG\r\n\x1a\n"

        assert client.post("/api/v1/auth/mfa/confirm", headers=headers, json={"secret": secret, "code": "000000"}).status_code == 400
        confirmed = client.post("/api/v1/auth/mfa/confirm", headers=headers, json={"secret": secret, "code": pyotp.TOTP(secret).now()})
        assert confirmed.status_code == 200
        assert confirmed.json()["mfa_enabled"] is True and len(confirmed.json()["backup_codes"]) >= 5


def _claims(token: str) -> dict:
    import base64
    import json

    payload = token.split(".")[1]
    return json.loads(base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4)))


def _seed_login_user(*, workspace: bool):
    from core.database.database import Base, SessionLocal, engine
    from core.security.auth import get_password_hash
    from db.models import SubscriptionTier, User, UserRole, UserStatus, Workspace

    email = f"claims-{uuid.uuid4().hex}@example.com"
    workspace_id = str(uuid.uuid4()) if workspace else None

    async def seed():
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        async with SessionLocal() as session:
            session.add(User(email=email, username=f"claims-{uuid.uuid4().hex[:10]}",
                             hashed_password=get_password_hash("CorrectHorseBatteryStaple1"),
                             role=UserRole.USER, status=UserStatus.ACTIVE))
            if workspace_id:
                session.add(Workspace(id=workspace_id, owner_id=email, name="Claims Workspace",
                                      slug=f"claims-{uuid.uuid4().hex[:10]}", tier=SubscriptionTier.FREE))
            await session.commit()

    asyncio.run(seed())
    return email, workspace_id


def test_login_and_refresh_tokens_carry_the_users_own_workspace():
    """CAPPO takes the tenant from this claim. Two accounts must never share one."""
    _set_test_env()
    from fastapi.testclient import TestClient
    from apps.api.main import app

    alice, alice_ws = _seed_login_user(workspace=True)
    bob, bob_ws = _seed_login_user(workspace=True)
    newcomer, _ = _seed_login_user(workspace=False)

    def login(client, email):
        response = client.post("/api/v1/auth/login", json={"email": email, "password": "CorrectHorseBatteryStaple1"})
        assert response.status_code == 200, response.text
        return response.json()

    with TestClient(app) as client:
        a, b, n = login(client, alice), login(client, bob), login(client, newcomer)

        assert _claims(a["access_token"])["workspace_id"] == alice_ws
        assert _claims(b["access_token"])["workspace_id"] == bob_ws
        assert _claims(a["access_token"])["workspace_id"] != _claims(b["access_token"])["workspace_id"]

        # No workspace yet: no workspace claim of any kind, and never the shared "default".
        newcomer_claims = _claims(n["access_token"])
        assert not any(key in newcomer_claims for key in ("workspace_id", "workspace", "tenant_id"))

        refreshed = client.post("/api/v1/auth/refresh", headers={"Authorization": f"Bearer {a['refresh_token']}"})
        assert refreshed.status_code == 200, refreshed.text
        assert _claims(refreshed.json()["access_token"])["workspace_id"] == alice_ws
