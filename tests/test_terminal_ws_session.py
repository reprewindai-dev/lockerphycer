"""The operator terminal websocket must honour session revocation, not just
the token's signature."""
import asyncio
import os
import uuid
from datetime import datetime, timedelta

import pytest


def _set_test_env():
    os.environ.setdefault("SECRET_KEY", "test-secret-key-test-secret-key-test-1234")
    os.environ.setdefault("ENVIRONMENT", "development")
    os.environ.setdefault("DEBUG", "true")
    os.environ["DATABASE_URL"] = "sqlite+aiosqlite:///./test_lockerphycer.db"


def test_terminal_websocket_refuses_a_revoked_session():
    _set_test_env()
    from fastapi.testclient import TestClient
    from starlette.websockets import WebSocketDisconnect

    from apps.api.main import app
    from apps.api.routers.terminal_ws import ADMIN_EMAIL
    from core.database.database import SessionLocal
    from core.security.auth import create_access_token, create_refresh_token, hash_token
    from db.models import UserSession

    token = create_access_token({"sub": ADMIN_EMAIL})
    session_id = str(uuid.uuid4())

    async def seed():
        async with SessionLocal() as db:
            db.add(UserSession(id=session_id, user_id=str(uuid.uuid4()), session_token_hash=hash_token(token),
                               refresh_token_hash=hash_token(create_refresh_token({"sub": ADMIN_EMAIL})),
                               expires_at=datetime.utcnow() + timedelta(hours=1)))
            await db.commit()

    async def revoke():
        async with SessionLocal() as db:
            (await db.get(UserSession, session_id)).is_active = False
            await db.commit()

    with TestClient(app) as client:
        asyncio.run(seed())
        with client.websocket_connect(f"/ws/terminal?token={token}") as ws:
            assert ws.receive_json()["type"] == "handshake"

        asyncio.run(revoke())
        with pytest.raises(WebSocketDisconnect):
            with client.websocket_connect(f"/ws/terminal?token={token}") as ws:
                ws.receive_json()

        # A validly signed admin token with no session at all is refused too.
        orphan = create_access_token({"sub": ADMIN_EMAIL})
        with pytest.raises(WebSocketDisconnect):
            with client.websocket_connect(f"/ws/terminal?token={orphan}") as ws:
                ws.receive_json()
