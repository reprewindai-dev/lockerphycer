import asyncio
import os
import uuid
from datetime import datetime, timedelta, timezone


def _set_test_env():
    os.environ.setdefault("SECRET_KEY", "test-secret-key-test-secret-key-test-1234")
    os.environ.setdefault("ENVIRONMENT", "development")
    os.environ.setdefault("DEBUG", "true")
    os.environ["DATABASE_URL"] = "sqlite+aiosqlite:///./test_lockerphycer.db"


def _seed_user(*, admin: bool = False, workspace: bool = False):
    _set_test_env()

    from core.database.database import Base, SessionLocal, engine
    from core.security.auth import (
        create_access_token,
        create_refresh_token,
        get_password_hash,
    )
    from db.models import (
        SubscriptionTier,
        User,
        UserRole,
        UserSession,
        UserStatus,
        Workspace,
    )

    email = f"workspace-{uuid.uuid4().hex}@example.com"
    workspace_id = str(uuid.uuid4()) if workspace else None

    async def seed():
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        async with SessionLocal() as session:
            user = User(
                email=email,
                username=f"workspace-{uuid.uuid4().hex[:10]}",
                hashed_password=get_password_hash("CorrectHorseBatteryStaple1"),
                role=UserRole.ADMIN if admin else UserRole.USER,
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
                    expires_at=datetime.now(timezone.utc).replace(tzinfo=None) + timedelta(hours=1),
                )
            )
            if workspace_id:
                session.add(
                    Workspace(
                        id=workspace_id,
                        owner_id=email,
                        name="Existing Workspace",
                        slug=f"existing-{uuid.uuid4().hex[:10]}",
                        tier=SubscriptionTier.FREE,
                    )
                )
            await session.commit()
        return email, access_token, workspace_id

    return asyncio.run(seed())


def test_workspace_onboarding_rotates_claim_and_is_idempotent():
    _set_test_env()
    from fastapi.testclient import TestClient

    from apps.api.main import app

    _, login_token, _ = _seed_user()
    login_headers = {"Authorization": f"Bearer {login_token}"}

    with TestClient(app) as client:
        before_rotation = client.get("/api/v1/auth/me", headers=login_headers)
        assert before_rotation.status_code == 200
        assert before_rotation.json()["workspace_id"] is None

        created = client.post(
            "/api/v1/workspace",
            headers=login_headers,
            json={
                "name": "Canary Workspace",
                "slug": f"canary-workspace-{uuid.uuid4().hex[:10]}",
            },
        )
        assert created.status_code in {200, 201}
        first = created.json()
        assert first["existing"] is False
        assert first["access_token"]
        assert first["refresh_token"]

        rotated_headers = {"Authorization": f"Bearer {first['access_token']}"}
        bound = client.get("/api/v1/auth/me", headers=rotated_headers)
        assert bound.status_code == 200
        assert bound.json()["workspace_id"] == first["id"]

        repeated = client.post(
            "/api/v1/workspace",
            headers=rotated_headers,
            json={"name": "Different Name", "slug": "different-slug"},
        )
        assert repeated.status_code in {200, 201}
        assert repeated.json()["existing"] is True
        assert repeated.json()["id"] == first["id"]

        old_session = client.get("/api/v1/auth/me", headers=login_headers)
        assert old_session.status_code == 401


def test_workspace_routes_accept_slashless_paths_and_preserve_admin_gate():
    _set_test_env()
    from fastapi.testclient import TestClient

    from apps.api.main import app

    _, admin_token, workspace_id = _seed_user(admin=True, workspace=True)
    _, user_token, _ = _seed_user()
    admin_headers = {"Authorization": f"Bearer {admin_token}"}
    user_headers = {"Authorization": f"Bearer {user_token}"}

    with TestClient(app) as client:
        slashless_list = client.get("/api/v1/workspace", headers=admin_headers)
        assert slashless_list.status_code == 200
        trailing_list = client.get("/api/v1/workspace/", headers=admin_headers)
        assert trailing_list.status_code == 200

        forbidden = client.get(f"/api/v1/workspace/{workspace_id}", headers=user_headers)
        assert forbidden.status_code == 403


def test_workspace_me_is_owner_readable_and_authenticated():
    _set_test_env()
    from fastapi.testclient import TestClient

    from apps.api.main import app

    _, owner_token, workspace_id = _seed_user(workspace=True)
    _, other_token, _ = _seed_user()

    with TestClient(app) as client:
        owner = client.get(
            "/api/v1/workspace/me",
            headers={"Authorization": f"Bearer {owner_token}"},
        )
        assert owner.status_code == 200
        assert owner.json()["id"] == workspace_id
        assert set(owner.json()) == {"id", "name", "slug", "tier", "is_active", "created_at"}

        other = client.get(
            "/api/v1/workspace/me",
            headers={"Authorization": f"Bearer {other_token}"},
        )
        assert other.status_code == 404
        assert other.json()["detail"] == "No workspace bound to this operator"

        unauthenticated = client.get("/api/v1/workspace/me")
        assert unauthenticated.status_code == 401
