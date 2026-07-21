import asyncio
import os
import uuid
from datetime import datetime, timedelta


def _set_test_env():
    os.environ.setdefault("SECRET_KEY", "test-secret-key-test-secret-key-test-1234")
    os.environ.setdefault("ENVIRONMENT", "development")
    os.environ.setdefault("DEBUG", "true")


def test_app_imports():
    _set_test_env()
    from apps.api.main import app

    assert app.title


def test_health_endpoint_starts_application():
    _set_test_env()
    from fastapi.testclient import TestClient
    from apps.api.main import app

    with TestClient(app) as client:
        response = client.get("/health")

    assert response.status_code == 200
    assert response.json()["status"] == "healthy"


def test_auth_session_lifecycle():
    _set_test_env()
    from fastapi.testclient import TestClient

    from apps.api.main import app

    email = f"user-{uuid.uuid4()}@example.com"
    password = "CorrectHorseBatteryStaple1"

    with TestClient(app) as client:
        register = client.post(
            "/api/v1/auth/register",
            json={
                "email": email,
                "username": f"user-{uuid.uuid4().hex[:8]}",
                "full_name": "Test User",
                "password": password,
            },
        )
        assert register.status_code == 200

        login = client.post(
            "/api/v1/auth/login",
            json={"email": email, "password": password},
        )
        assert login.status_code == 200
        tokens = login.json()
        headers = {"Authorization": f"Bearer {tokens['access_token']}"}

        me = client.get("/api/v1/auth/me", headers=headers)
        assert me.status_code == 200

        logout = client.post("/api/v1/auth/logout", headers=headers)
        assert logout.status_code == 200

        revoked = client.get("/api/v1/auth/me", headers=headers)
        assert revoked.status_code == 401


def test_business_control_plane_endpoints():
    _set_test_env()
    from fastapi.testclient import TestClient

    from apps.api.main import app
    from core.database.database import SessionLocal
    from core.security.auth import create_access_token, create_refresh_token, get_password_hash
    from db.models import SubscriptionTier, User, UserRole, UserSession, UserStatus, Workspace

    email = f"admin-{uuid.uuid4()}@example.com"
    workspace_id = str(uuid.uuid4())

    async def seed_records():
        async with SessionLocal() as session:
            user = User(
                email=email,
                username=f"admin-{uuid.uuid4().hex[:8]}",
                hashed_password=get_password_hash("CorrectHorseBatteryStaple1"),
                role=UserRole.ADMIN,
                status=UserStatus.ACTIVE,
            )
            session.add(user)
            await session.flush()
            access_token = create_access_token({"sub": email})
            refresh_token = create_refresh_token({"sub": email})
            session.add(
                UserSession(
                    user_id=user.id,
                    session_token=access_token,
                    refresh_token=refresh_token,
                    ip_address="127.0.0.1",
                    user_agent="pytest",
                    expires_at=datetime.utcnow() + timedelta(hours=1),
                )
            )
            session.add(
                Workspace(
                    id=workspace_id,
                    owner_id=email,
                    name="Acme Health",
                    slug=f"acme-health-{uuid.uuid4().hex[:8]}",
                    tier=SubscriptionTier.SOVEREIGN,
                )
            )
            await session.commit()
            return access_token

    token = asyncio.run(seed_records())
    headers = {"Authorization": f"Bearer {token}"}

    with TestClient(app) as client:
        seed = client.post("/api/v1/business/compliance-mappings/seed", headers=headers)
        assert seed.status_code == 200

        mappings = client.get("/api/v1/business/compliance-mappings", headers=headers)
        assert mappings.status_code == 200
        assert mappings.json()["total"] >= 1

        usage = client.post(
            "/api/v1/business/byok-usage",
            headers=headers,
            json={
                "workspace_id": workspace_id,
                "provider": "openai",
                "model": "gpt-4.1-mini",
                "route_type": "byok",
                "prompt_tokens": 1000,
                "completion_tokens": 500,
                "request_count": 2,
                "provider_cost_cents": 25,
                "baseline_cost_cents": 100,
                "cache_savings_cents": 30,
                "local_route_savings_cents": 45,
            },
        )
        assert usage.status_code == 200

        dashboard = client.get(f"/api/v1/business/byok-cost/{workspace_id}", headers=headers)
        assert dashboard.status_code == 200
        assert dashboard.json()["totals"]["total_savings_cents"] >= 75

        quote = client.post(
            "/api/v1/business/managed-service/quote",
            headers=headers,
            json={"environment_count": 2, "cluster_count": 2, "node_count": 10, "regulated_workload": True},
        )
        assert quote.status_code == 200
        assert quote.json()["monthly_fee_cents"] > 150000
