def test_app_imports():
    from apps.api.main import app

    assert app.title


def test_health_endpoint_starts_application():
    from fastapi.testclient import TestClient
    from apps.api.main import app

    with TestClient(app) as client:
        response = client.get("/health")

    assert response.status_code == 200
    assert response.json()["status"] == "healthy"


def test_business_control_plane_endpoints():
    import asyncio
    import uuid

    from fastapi.testclient import TestClient

    from apps.api.main import app
    from core.database.database import SessionLocal
    from core.security.auth import create_access_token, get_password_hash
    from db.models import SubscriptionTier, User, UserRole, UserStatus, Workspace

    email = f"admin-{uuid.uuid4()}@example.com"
    workspace_id = str(uuid.uuid4())

    async def seed_records():
        async with SessionLocal() as session:
            session.add(
                User(
                    email=email,
                    username=f"admin-{uuid.uuid4().hex[:8]}",
                    hashed_password=get_password_hash("CorrectHorseBatteryStaple1"),
                    role=UserRole.ADMIN,
                    status=UserStatus.ACTIVE,
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

    with TestClient(app):
        asyncio.run(seed_records())

        token = create_access_token({"sub": email})
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
