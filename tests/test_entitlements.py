"""Entitlements: Welcome clock, monthly reset, consumption order, idempotency,
exhausted denial, Welcome non-recurrence, activation events and HTTP surface."""

import asyncio
import os
import uuid
from datetime import datetime, timedelta

import pytest

os.environ.setdefault("SECRET_KEY", "test-secret-key-test-secret-key-test-1234")
os.environ.setdefault("ENVIRONMENT", "development")
os.environ.setdefault("DEBUG", "true")
os.environ["DATABASE_URL"] = "sqlite+aiosqlite:///./test_lockerphycer.db"

T0 = datetime(2026, 9, 1, 12, 0, 0)
SERVICE_TOKEN = "svc-token-for-tests-0123456789"


@pytest.fixture(autouse=True)
def entitlement_env(monkeypatch):
    from core.entitlements.config import get_entitlement_settings

    monkeypatch.setenv("ENTITLEMENTS_INTERNAL_TOKEN", SERVICE_TOKEN)
    monkeypatch.setenv("ENTITLEMENTS_UPGRADE_PATH", "/configured/upgrade")
    get_entitlement_settings.cache_clear()
    yield
    get_entitlement_settings.cache_clear()


def run(coro):
    return asyncio.run(coro)


async def _tables():
    from core.database.database import Base, engine

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


async def _workspace(owner: str | None = None, created_at: datetime = T0, active: bool = True):
    from core.database.database import SessionLocal
    from db.models import SubscriptionTier, Workspace

    await _tables()
    ws_id = str(uuid.uuid4())
    async with SessionLocal() as db:
        db.add(Workspace(
            id=ws_id, owner_id=owner or f"owner-{uuid.uuid4().hex}@example.com",
            name="ws", slug=f"ws-{uuid.uuid4().hex[:12]}", tier=SubscriptionTier.FREE,
            is_active=active, created_at=created_at,
        ))
        await db.commit()
    return ws_id


async def _ensure(ws_id: str, now: datetime):
    from core.database.database import SessionLocal
    from core.entitlements import service as S
    from db.models import Workspace

    async with SessionLocal() as db:
        ws = await db.get(Workspace, ws_id)
        ent = await S.ensure_entitlement(db, ws, now=now)
        snap = S.snapshot(ent, now)
        await db.commit()
        return snap


async def _debit(ws_id, action, key, now):
    from core.database.database import SessionLocal
    from core.entitlements import service as S

    async with SessionLocal() as db:
        return await S.debit(db, ws_id, action, idempotency_key=key, now=now, principal="agent-a")


async def _ledger(ws_id):
    from sqlalchemy import select

    from core.database.database import SessionLocal
    from db.models import CreditLedgerEntry

    async with SessionLocal() as db:
        rows = (await db.execute(
            select(CreditLedgerEntry).where(CreditLedgerEntry.workspace_id == ws_id)
            .order_by(CreditLedgerEntry.created_at)
        )).scalars().all()
        return [(r.entry_type, r.action_type, r.credits, r.allowance_debit, r.topup_debit, r.idempotency_key) for r in rows]


async def _events(ws_id):
    from sqlalchemy import select

    from core.database.database import SessionLocal
    from db.models import ActivationEvent

    async with SessionLocal() as db:
        return [e.event_name for e in (await db.execute(
            select(ActivationEvent).where(ActivationEvent.workspace_id == ws_id))).scalars()]


async def _to_developer(ws_id):
    """Create entitlement at T0 and return the first Developer instant."""
    await _ensure(ws_id, T0)
    after = T0 + timedelta(days=14)
    await _ensure(ws_id, after)
    return after


# ---------------------------------------------------------------------------


def test_welcome_clock_expiry_with_frozen_time():
    from freezegun import freeze_time

    from core.database.database import SessionLocal
    from core.entitlements import service as S
    from db.models import Workspace

    ws_id = run(_workspace())

    async def snap_real_clock():
        async with SessionLocal() as db:
            ent = await S.ensure_entitlement(db, await db.get(Workspace, ws_id))
            out = S.snapshot(ent)
            await db.commit()
            return out

    with freeze_time(T0, real_asyncio=True):
        s = run(snap_real_clock())
        assert s["welcome"]["active"] is True
        assert s["welcome"]["days_left"] == 14
        assert s["effective_tier"] == "welcome"
        assert s["balances"]["allowance_total"] == 100_000
        assert s["welcome"]["message"] == "Full Veklom access for 14 days, safe-use limits apply."
    with freeze_time(T0 + timedelta(days=13, hours=23), real_asyncio=True):
        s = run(snap_real_clock())
        assert s["welcome"]["active"] is True and s["welcome"]["days_left"] == 1
    with freeze_time(T0 + timedelta(days=14), real_asyncio=True):
        s = run(snap_real_clock())
        assert s["welcome"]["active"] is False
        assert s["plan"] == "developer" and s["effective_tier"] == "developer"
        assert s["balances"]["allowance_total"] == 250
        assert s["period"]["start"] == (T0 + timedelta(days=14)).isoformat()
        assert s["limits"]["users"] == 1 and s["limits"]["agents"] == 1
        assert s["limits"]["retention_days"] == 7
    with freeze_time(T0 + timedelta(days=15), real_asyncio=True):
        run(snap_real_clock())
    assert run(_events(ws_id)).count("welcome_ended") == 1
    assert "unlimited" not in repr(s).lower()


def test_monthly_reset_keeps_topups():
    from core.database.database import SessionLocal
    from core.entitlements import service as S

    ws_id = run(_workspace())
    dev = run(_to_developer(ws_id))
    run(_debit(ws_id, "governed_execution", "k-" + uuid.uuid4().hex, dev + timedelta(hours=1)))

    async def topup():
        async with SessionLocal() as db:
            await S.grant_topup(db, ws_id, 40, idempotency_key="t-" + uuid.uuid4().hex,
                                settlement_rail="manual", now=dev + timedelta(hours=2))
    run(topup())

    s = run(_ensure(ws_id, dev + timedelta(days=29)))
    assert s["balances"]["allowance_used"] == 25
    s = run(_ensure(ws_id, dev + timedelta(days=30)))
    assert s["balances"]["allowance_used"] == 0
    assert s["balances"]["allowance_total"] == 250
    assert s["balances"]["topup_balance"] == 40  # top-ups never expire
    # Skipping several periods rolls to the correct current period once.
    s = run(_ensure(ws_id, dev + timedelta(days=95)))
    assert s["period"]["start"] == (dev + timedelta(days=90)).isoformat()
    grants = [e for e in run(_ledger(ws_id)) if e[0] == "grant"]
    assert len(grants) == 4  # welcome, developer, +30d, +90d


def test_allowance_consumed_before_topup():
    from core.database.database import SessionLocal
    from core.entitlements import service as S

    ws_id = run(_workspace())
    dev = run(_to_developer(ws_id))

    async def topup():
        async with SessionLocal() as db:
            await S.grant_topup(db, ws_id, 100, idempotency_key="t-" + uuid.uuid4().hex,
                                settlement_rail="manual", now=dev)
    run(topup())
    for i in range(16):  # 16 x 15 = 240 of the 250 allowance
        r = run(_debit(ws_id, "governed_action", f"ga-{ws_id}-{i}", dev + timedelta(minutes=i + 1)))
        assert r.charged and r.balance["topup_balance"] == 100
    r = run(_debit(ws_id, "governed_execution", f"ge-{ws_id}", dev + timedelta(hours=1)))
    last = run(_ledger(ws_id))[-1]
    assert last[0] == "debit" and last[2] == 25
    assert last[3] == 10 and last[4] == 15  # 10 from allowance, 15 from top-up
    assert r.balance["allowance_remaining"] == 0 and r.balance["topup_balance"] == 85


def test_idempotent_debit_never_double_charges():
    from core.entitlements import service as S

    ws_id = run(_workspace())
    now = T0 + timedelta(hours=1)
    run(_ensure(ws_id, T0))
    key = "cappo:execute:m1:t1"
    first = run(_debit(ws_id, "governed_execution", key, now))
    second = run(_debit(ws_id, "governed_execution", key, now + timedelta(seconds=5)))
    assert first.charged and not first.replay
    assert second.replay and second.entry_id == first.entry_id
    debits = [e for e in run(_ledger(ws_id)) if e[0] == "debit"]
    assert len(debits) == 1
    assert run(_ensure(ws_id, now))["balances"]["allowance_used"] == 25

    other = run(_workspace())
    run(_ensure(other, T0))
    with pytest.raises(S.IdempotencyConflict):
        run(_debit(other, "governed_execution", key, now))


def test_reversal_refunds_once():
    from core.database.database import SessionLocal
    from core.entitlements import service as S

    ws_id = run(_workspace())
    run(_ensure(ws_id, T0))
    key = "cappo:action:m2:t2:counter.increment"
    run(_debit(ws_id, "governed_action", key, T0 + timedelta(minutes=1)))

    async def rev():
        async with SessionLocal() as db:
            return await S.reverse(db, key, now=T0 + timedelta(minutes=2))
    assert run(rev())["replay"] is False
    assert run(rev())["replay"] is True
    assert run(_ensure(ws_id, T0 + timedelta(minutes=3)))["balances"]["allowance_used"] == 0


def test_exhausted_denial_is_structured_and_reads_fail_safe():
    from core.entitlements import service as S

    ws_id = run(_workspace())
    dev = run(_to_developer(ws_id))
    for i in range(10):  # 10 x 25 = 250
        run(_debit(ws_id, "governed_execution", f"ex-{ws_id}-{i}", dev + timedelta(minutes=i + 1)))
    with pytest.raises(S.CreditsExhausted) as exc:
        run(_debit(ws_id, "governed_execution", f"ex-{ws_id}-over", dev + timedelta(hours=1)))
    body = exc.value.body
    assert exc.value.status_code == 402
    assert body["code"] == "CREDITS_EXHAUSTED"
    assert body["plan"] == "developer" and body["in_welcome"] is False
    assert body["required_credits"] == 25
    assert body["balance"]["total_available"] == 0
    assert body["upgrade_path"] == "/configured/upgrade"
    assert body["topups_allowed"] is True
    # Verification reads continue (not charged) when exhausted.
    read = run(_debit(ws_id, "verification_read", f"rd-{ws_id}", dev + timedelta(hours=2)))
    assert read.allowed and not read.charged and read.credits == 0


def test_welcome_daily_safe_use_limit(monkeypatch):
    from core.entitlements import service as S
    from core.entitlements.config import get_entitlement_settings

    monkeypatch.setenv("WELCOME_DAILY_CREDIT_CAP", "50")
    get_entitlement_settings.cache_clear()
    ws_id = run(_workspace())
    run(_ensure(ws_id, T0))
    run(_debit(ws_id, "governed_execution", f"d1-{ws_id}", T0 + timedelta(minutes=1)))
    run(_debit(ws_id, "governed_execution", f"d2-{ws_id}", T0 + timedelta(minutes=2)))
    with pytest.raises(S.SafeUseLimitReached) as exc:
        run(_debit(ws_id, "governed_execution", f"d3-{ws_id}", T0 + timedelta(minutes=3)))
    assert exc.value.status_code == 429
    # Window slides: 24h later it is allowed again.
    assert run(_debit(ws_id, "governed_execution", f"d4-{ws_id}", T0 + timedelta(days=1, minutes=5))).charged


def test_welcome_never_recurs_for_owner_or_workspace():
    owner = f"repeat-{uuid.uuid4().hex}@example.com"
    first = run(_workspace(owner=owner, active=False))
    s1 = run(_ensure(first, T0))
    assert s1["welcome"]["active"] is True
    # Re-ensuring the same workspace later never restarts the clock.
    s1b = run(_ensure(first, T0 + timedelta(days=20)))
    assert s1b["welcome"]["active"] is False and s1b["welcome"]["started_at"] == T0.isoformat()
    # A new workspace for the same owner does not get a second Welcome.
    second = run(_workspace(owner=owner.upper(), created_at=T0 + timedelta(days=21)))
    s2 = run(_ensure(second, T0 + timedelta(days=21)))
    assert s2["welcome"]["active"] is False and s2["welcome"]["eligible"] is False
    assert s2["plan"] == "developer" and s2["balances"]["allowance_total"] == 250


def test_trial_converted_on_paid_plan():
    from core.database.database import SessionLocal
    from core.entitlements import service as S

    ws_id = run(_workspace())
    run(_ensure(ws_id, T0))

    async def upgrade():
        async with SessionLocal() as db:
            ent = await S.set_plan(db, ws_id, "pro", now=T0 + timedelta(days=3))
            return S.snapshot(ent, T0 + timedelta(days=3))
    s = run(upgrade())
    assert s["plan"] == "pro" and s["welcome"]["active"] is False
    assert s["balances"]["allowance_total"] == 5000 and s["limits"]["users"] == 5
    assert "trial_converted" in run(_events(ws_id))


def test_usage_summary_counts():
    from core.database.database import SessionLocal
    from core.entitlements import service as S

    ws_id = run(_workspace())
    run(_ensure(ws_id, T0))
    run(_debit(ws_id, "governed_execution", f"u1-{ws_id}", T0 + timedelta(minutes=1)))
    run(_debit(ws_id, "governed_action", f"u2-{ws_id}", T0 + timedelta(minutes=2)))
    run(_debit(ws_id, "verification_read", f"u3-{ws_id}", T0 + timedelta(minutes=3)))

    async def go():
        async with SessionLocal() as db:
            await S.reverse(db, f"u2-{ws_id}", now=T0 + timedelta(minutes=4))
            return await S.usage_summary(db, ws_id, since=T0, until=T0 + timedelta(days=1))
    u = run(go())
    assert u["governed_actions"] == 1 and u["governed_executions"] == 1
    assert u["denied_actions"] == 1 and u["verification_reads"] == 1
    assert u["credits_used"] == 30 and u["active_agents"] == 1 and u["receipts"] == 1


# --- HTTP surface ------------------------------------------------------------


def _seed_session(workspace_created: datetime | None = None):
    from core.database.database import SessionLocal
    from core.security.auth import create_access_token, create_refresh_token, get_password_hash
    from db.models import SubscriptionTier, User, UserRole, UserSession, UserStatus, Workspace

    email = f"ent-{uuid.uuid4().hex}@example.com"
    ws_id = str(uuid.uuid4())

    async def seed():
        await _tables()
        async with SessionLocal() as db:
            user = User(email=email, username=f"ent-{uuid.uuid4().hex[:10]}",
                        hashed_password=get_password_hash("CorrectHorseBatteryStaple1"),
                        role=UserRole.USER, status=UserStatus.ACTIVE)
            db.add(user)
            await db.flush()
            token = create_access_token({"sub": email, "workspace_id": ws_id})
            db.add(UserSession(user_id=user.id, session_token=token,
                               refresh_token=create_refresh_token({"sub": email}),
                               expires_at=datetime.utcnow() + timedelta(hours=1)))
            db.add(Workspace(id=ws_id, owner_id=email, name="w", slug=f"w-{uuid.uuid4().hex[:10]}",
                             tier=SubscriptionTier.FREE,
                             created_at=workspace_created or datetime.utcnow()))
            await db.commit()
        return token, ws_id

    return run(seed())


def test_get_entitlements_endpoint():
    from fastapi.testclient import TestClient

    from apps.api.main import app

    token, ws_id = _seed_session()
    with TestClient(app) as client:
        r = client.get("/api/v1/entitlements", headers={"Authorization": f"Bearer {token}"})
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["workspace_id"] == ws_id
        assert body["welcome"]["active"] is True and body["welcome"]["days_left"] == 14
        assert body["balances"]["total_available"] == 100_000
        assert body["credit_schedule"]["governed_execution"] == 25
        assert body["upgrade_path"] == "/configured/upgrade"
        assert "unlimited" not in r.text.lower()
        u = client.get("/api/v1/entitlements/usage", headers={"Authorization": f"Bearer {token}"})
        assert u.status_code == 200 and u.json()["workspace_id"] == ws_id


def test_internal_meter_requires_token_and_returns_402():
    from fastapi.testclient import TestClient

    from apps.api.main import app

    _token, ws_id = _seed_session(workspace_created=datetime.utcnow() - timedelta(days=30))
    body = {"workspace_id": ws_id, "action_type": "governed_execution",
            "idempotency_key": "cappo:execute:x:y", "principal": "jwt:test"}
    with TestClient(app) as client:
        assert client.post("/api/v1/internal/entitlements/meter", json=body).status_code == 401
        h = {"X-Veklom-Service-Token": SERVICE_TOKEN}
        for i in range(10):
            ok = client.post("/api/v1/internal/entitlements/meter", headers=h,
                             json={**body, "idempotency_key": f"cappo:execute:{ws_id}:{i}"})
            assert ok.status_code == 200 and ok.json()["charged"] is True
        denied = client.post("/api/v1/internal/entitlements/meter", headers=h,
                             json={**body, "idempotency_key": f"cappo:execute:{ws_id}:over"})
        assert denied.status_code == 402
        err = denied.json()["error"]
        assert err["code"] == "CREDITS_EXHAUSTED" and err["plan"] == "developer"
        ev = client.post("/api/v1/internal/activation-events", headers=h,
                         json={"event_name": "first_governed_execution", "workspace_id": ws_id})
        assert ev.status_code == 200 and ev.json()["recorded"] is True
        again = client.post("/api/v1/internal/activation-events", headers=h,
                            json={"event_name": "first_governed_execution", "workspace_id": ws_id})
        assert again.json()["recorded"] is False


def test_agent_limit_on_machine_tokens_after_welcome():
    from fastapi.testclient import TestClient

    from apps.api.main import app

    token, ws_id = _seed_session(workspace_created=datetime.utcnow() - timedelta(days=30))
    h = {"Authorization": f"Bearer {token}"}
    with TestClient(app) as client:
        first = client.post("/api/v1/machine-tokens", headers=h, json={"name": "a1", "workspace_id": ws_id})
        assert first.status_code == 200, first.text
        second = client.post("/api/v1/machine-tokens", headers=h, json={"name": "a2", "workspace_id": ws_id})
        assert second.status_code == 403
        assert second.json()["error"]["code"] == "PLAN_LIMIT_REACHED"
