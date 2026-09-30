"""Stripe TEST-mode integration with an in-memory fake Stripe (httpx.MockTransport).

No request leaves the process. Covers setup idempotency + live-key refusal,
checkout session shape, signature failure, idempotent replay, plan change,
top-up credit grant, past_due handling, renewal and cancel -> Developer.
"""

import asyncio
import json
import os
import uuid
from datetime import datetime, timedelta
from urllib.parse import parse_qsl

import httpx
import pytest

os.environ.setdefault("SECRET_KEY", "test-secret-key-test-secret-key-test-1234")
os.environ.setdefault("ENVIRONMENT", "development")
os.environ.setdefault("DEBUG", "true")
os.environ["DATABASE_URL"] = "sqlite+aiosqlite:///./test_lockerphycer.db"

TEST_KEY = "sk_test_unit_" + uuid.uuid4().hex  # fake; transport is mocked
WEBHOOK_SECRET = "whsec_unit_" + uuid.uuid4().hex


class FakeStripe:
    def __init__(self):
        self.products, self.prices, self.sessions, self.calls = {}, {}, [], []

    def handler(self, request: httpx.Request) -> httpx.Response:
        path, method = request.url.path, request.method
        form = dict(parse_qsl(request.content.decode())) if request.content else {}
        self.calls.append((method, path, form))
        if path.startswith("/v1/products/") and method == "GET":
            pid = path.rsplit("/", 1)[1]
            if pid not in self.products:
                return httpx.Response(404, json={"error": {"type": "invalid_request_error"}})
            return httpx.Response(200, json=self.products[pid])
        if path == "/v1/products" and method == "POST":
            self.products[form["id"]] = {"id": form["id"], "name": form["name"], "active": True}
            return httpx.Response(200, json=self.products[form["id"]])
        if path.startswith("/v1/products/") and method == "POST":
            p = self.products[path.rsplit("/", 1)[1]]
            p.update(name=form.get("name", p["name"]))
            return httpx.Response(200, json=p)
        if path == "/v1/prices" and method == "GET":
            key = request.url.params.get("lookup_keys[]")
            hits = [p for p in self.prices.values() if p.get("lookup_key") == key and p["active"]]
            return httpx.Response(200, json={"data": hits[:1]})
        if path == "/v1/prices" and method == "POST":
            pid = f"price_{uuid.uuid4().hex[:10]}"
            if form.get("transfer_lookup_key") == "true":
                for p in self.prices.values():
                    if p.get("lookup_key") == form["lookup_key"]:
                        p["lookup_key"] = None
            meta = {k[9:-1]: v for k, v in form.items() if k.startswith("metadata[")}
            self.prices[pid] = {"id": pid, "product": form["product"], "currency": form["currency"],
                                "unit_amount": int(form["unit_amount"]), "lookup_key": form["lookup_key"],
                                "recurring": {"interval": form["recurring[interval]"]} if "recurring[interval]" in form else None,
                                "metadata": meta, "active": True}
            return httpx.Response(200, json=self.prices[pid])
        if path.startswith("/v1/prices/") and method == "POST":
            p = self.prices[path.rsplit("/", 1)[1]]
            if "active" in form:
                p["active"] = form["active"] == "true"
            p["metadata"].update({k[9:-1]: v for k, v in form.items() if k.startswith("metadata[")})
            return httpx.Response(200, json=p)
        if path == "/v1/checkout/sessions" and method == "POST":
            sid = f"cs_test_{uuid.uuid4().hex[:10]}"
            self.sessions.append(form)
            return httpx.Response(200, json={"id": sid, "url": f"https://checkout.stripe.test/{sid}"})
        if path == "/v1/billing_portal/sessions" and method == "POST":
            return httpx.Response(200, json={"url": "https://billing.stripe.test/p"})
        return httpx.Response(400, json={"error": {"type": "unhandled"}})

    def client(self):
        from core.entitlements.stripe_billing import StripeClient

        return StripeClient(TEST_KEY, api_base="https://stripe.test", transport=httpx.MockTransport(self.handler))


@pytest.fixture()
def fake_stripe(monkeypatch):
    from core.config.settings import settings
    from core.entitlements import stripe_billing
    from core.entitlements.config import get_entitlement_settings

    get_entitlement_settings.cache_clear()
    fake = FakeStripe()
    monkeypatch.setattr(stripe_billing, "client_factory", fake.client)
    monkeypatch.setattr(settings, "STRIPE_WEBHOOK_SECRET", WEBHOOK_SECRET)
    from scripts.stripe_setup import run as setup_run
    setup_run(fake.client(), log=lambda *_: None)
    yield fake
    get_entitlement_settings.cache_clear()


def run(coro):
    return asyncio.run(coro)


def _seed(created=None):
    from core.database.database import Base, SessionLocal, engine
    from core.security.auth import create_access_token, create_refresh_token, get_password_hash
    from db.models import SubscriptionTier, User, UserRole, UserSession, UserStatus, Workspace

    email = f"stripe-{uuid.uuid4().hex}@example.com"
    ws_id = str(uuid.uuid4())

    async def seed():
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        async with SessionLocal() as db:
            user = User(email=email, username=f"s-{uuid.uuid4().hex[:10]}",
                        hashed_password=get_password_hash("CorrectHorseBatteryStaple1"),
                        role=UserRole.USER, status=UserStatus.ACTIVE)
            db.add(user)
            await db.flush()
            token = create_access_token({"sub": email, "workspace_id": ws_id})
            db.add(UserSession(user_id=user.id, session_token=token,
                               refresh_token=create_refresh_token({"sub": email}),
                               expires_at=datetime.utcnow() + timedelta(hours=1)))
            db.add(Workspace(id=ws_id, owner_id=email, name="s", slug=f"s-{uuid.uuid4().hex[:10]}",
                             tier=SubscriptionTier.FREE, created_at=created or datetime.utcnow()))
            await db.commit()
        return token, ws_id

    return run(seed())


def _post_event(client, event, secret=WEBHOOK_SECRET, sig=None):
    from core.entitlements.stripe_billing import sign_payload

    payload = json.dumps(event).encode()
    headers = {"Content-Type": "application/json",
               "Stripe-Signature": sig if sig is not None else sign_payload(payload, secret)}
    return client.post("/api/v1/billing/stripe/webhook", content=payload, headers=headers)


def _event(etype, obj):
    return {"id": f"evt_{uuid.uuid4().hex}", "type": etype, "data": {"object": obj}}


def _state(ws_id):
    from core.database.database import SessionLocal
    from core.entitlements import service as S
    from db.models import Workspace

    async def go():
        async with SessionLocal() as db:
            ws = await db.get(Workspace, ws_id)
            ent = await S.ensure_entitlement(db, ws)
            snap = S.snapshot(ent)
            await db.commit()
            return snap, ws.stripe_customer_id, ws.stripe_subscription_id, ws.subscription_status
    return run(go())


def _events(ws_id):
    from sqlalchemy import select

    from core.database.database import SessionLocal
    from db.models import ActivationEvent

    async def go():
        async with SessionLocal() as db:
            return [e.event_name for e in (await db.execute(
                select(ActivationEvent).where(ActivationEvent.workspace_id == ws_id))).scalars()]
    return run(go())


# ---------------------------------------------------------------------------


def test_setup_is_idempotent_and_refuses_live_keys(fake_stripe):
    from core.entitlements.stripe_billing import StripeConfigError, StripeClient
    from scripts.stripe_setup import run as setup_run

    before = [c for c in fake_stripe.calls if c[0] == "POST"]
    setup_run(fake_stripe.client(), log=lambda *_: None)
    after = [c for c in fake_stripe.calls if c[0] == "POST"]
    assert before == after  # second run changes nothing
    prices = {p["lookup_key"]: p for p in fake_stripe.prices.values() if p["lookup_key"]}
    assert prices["veklom_pro_monthly"]["unit_amount"] == 9900
    assert prices["veklom_pro_monthly"]["recurring"] == {"interval": "month"}
    assert prices["veklom_team_monthly"]["unit_amount"] == 39900
    assert prices["veklom_topup_50"]["recurring"] is None
    assert prices["veklom_topup_500"]["metadata"]["credits"] == "50000"
    assert set(fake_stripe.products) == {"veklom_pro", "veklom_team", "veklom_credits_topup"}
    with pytest.raises(StripeConfigError):
        StripeClient("sk_live_" + "x" * 20)
    os.environ["STRIPE_SECRET_KEY"] = "sk_live_" + "y" * 20
    try:
        with pytest.raises(SystemExit):
            setup_run(None)
    finally:
        del os.environ["STRIPE_SECRET_KEY"]


def test_checkout_session_carries_workspace(fake_stripe):
    from fastapi.testclient import TestClient

    from apps.api.main import app
    from core.config.settings import settings

    token, ws_id = _seed()
    h = {"Authorization": f"Bearer {token}"}
    with TestClient(app) as client:
        r = client.post("/api/v1/billing/checkout", headers=h, json={"kind": "pro"})
        assert r.status_code == 200, r.text
        assert r.json()["url"].startswith("https://checkout.stripe.test/")
        s = fake_stripe.sessions[-1]
        assert s["mode"] == "subscription" and s["client_reference_id"] == ws_id
        assert s["metadata[workspace_id]"] == ws_id and s["subscription_data[metadata][workspace_id]"] == ws_id
        assert s["success_url"].startswith(settings.FRONTEND_URL.rstrip("/") + "/os?")
        r = client.post("/api/v1/billing/checkout", headers=h, json={"kind": "topup_50"})
        assert r.status_code == 200
        s = fake_stripe.sessions[-1]
        assert s["mode"] == "payment" and s["metadata[credits]"] == "5000"
        assert client.post("/api/v1/billing/checkout", headers=h, json={"kind": "enterprise"}).status_code == 422


def test_webhook_rejects_bad_signatures(fake_stripe):
    from fastapi.testclient import TestClient

    from apps.api.main import app

    _t, ws_id = _seed()
    ev = _event("invoice.payment_failed", {"customer": "cus_x", "metadata": {"workspace_id": ws_id}})
    with TestClient(app) as client:
        assert _post_event(client, ev, secret="whsec_wrong").status_code == 400
        assert _post_event(client, ev, sig="").status_code == 400
        assert _post_event(client, ev, sig="t=1,v1=deadbeef").status_code == 400
    assert _state(ws_id)[3] == "inactive"


def test_topup_webhook_grants_credits_once(fake_stripe):
    from fastapi.testclient import TestClient

    from apps.api.main import app

    _t, ws_id = _seed()
    ev = _event("checkout.session.completed", {
        "id": f"cs_test_{uuid.uuid4().hex[:8]}", "object": "checkout.session", "mode": "payment",
        "payment_status": "paid", "customer": "cus_topup", "client_reference_id": ws_id,
        "payment_intent": "pi_test_1", "metadata": {"workspace_id": ws_id, "kind": "topup_50", "credits": "5000"}})
    with TestClient(app) as client:
        first = _post_event(client, ev)
        assert first.status_code == 200 and first.json()["duplicate"] is False
        replay = _post_event(client, ev)
        assert replay.status_code == 200 and replay.json()["duplicate"] is True
    snap, customer, _sub, _st = _state(ws_id)
    assert snap["balances"]["topup_balance"] == 5000
    assert customer == "cus_topup"
    assert "funding_method_added" in _events(ws_id)


def test_subscription_lifecycle_plan_change_past_due_renewal_cancel(fake_stripe):
    from fastapi.testclient import TestClient

    from apps.api.main import app

    _t, ws_id = _seed()
    sub_id = f"sub_test_{uuid.uuid4().hex[:8]}"
    with TestClient(app) as client:
        r = _post_event(client, _event("checkout.session.completed", {
            "id": f"cs_test_{uuid.uuid4().hex[:8]}", "object": "checkout.session", "mode": "subscription",
            "payment_status": "paid", "customer": "cus_sub", "subscription": sub_id,
            "client_reference_id": ws_id, "metadata": {"workspace_id": ws_id, "kind": "pro"}}))
        assert r.status_code == 200, r.text
        snap, customer, sub, status = _state(ws_id)
        assert snap["plan"] == "pro" and snap["balances"]["allowance_total"] == 5000
        assert snap["welcome"]["active"] is False
        assert (customer, sub, status) == ("cus_sub", sub_id, "active")
        assert "trial_converted" in _events(ws_id)

        # Upgrade to Team via subscription.updated (price lookup_key).
        _post_event(client, _event("customer.subscription.updated", {
            "id": sub_id, "object": "subscription", "status": "active", "customer": "cus_sub",
            "items": {"data": [{"price": {"lookup_key": "veklom_team_monthly"}}]}}))
        assert _state(ws_id)[0]["plan"] == "team"

        # Payment failure: past_due, no downgrade.
        _post_event(client, _event("invoice.payment_failed", {"customer": "cus_sub", "subscription": sub_id}))
        snap, _c, _s, status = _state(ws_id)
        assert status == "past_due" and snap["plan"] == "team"

        # Renewal resets the allowance (idempotent per invoice).
        inv = _event("invoice.paid", {"id": "in_test_1", "customer": "cus_sub", "subscription": sub_id,
                                      "billing_reason": "subscription_cycle"})
        assert _post_event(client, inv).json()["result"] == "allowance_reset"
        assert _post_event(client, inv).json()["duplicate"] is True
        assert _state(ws_id)[3] == "active"

        # Cancel -> Developer (free).
        _post_event(client, _event("customer.subscription.deleted", {
            "id": sub_id, "object": "subscription", "status": "canceled", "customer": "cus_sub"}))
        snap, _c, _s, status = _state(ws_id)
        assert snap["plan"] == "developer" and snap["balances"]["allowance_total"] == 250
        assert status == "canceled"


def test_unpaid_subscription_update_downgrades(fake_stripe):
    from fastapi.testclient import TestClient

    from apps.api.main import app

    _t, ws_id = _seed()
    with TestClient(app) as client:
        _post_event(client, _event("checkout.session.completed", {
            "id": "cs_test_u", "mode": "subscription", "payment_status": "paid", "customer": "cus_u",
            "subscription": "sub_u_" + ws_id[:8], "metadata": {"workspace_id": ws_id, "kind": "team"}}))
        _post_event(client, _event("customer.subscription.updated", {
            "id": "sub_u_" + ws_id[:8], "object": "subscription", "status": "unpaid", "customer": "cus_u"}))
    snap, _c, _s, status = _state(ws_id)
    assert snap["plan"] == "developer" and status == "unpaid"
