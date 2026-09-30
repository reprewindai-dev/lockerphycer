"""Stripe (TEST mode) checkout, portal and webhook processing.

* Keys are read from core.config.settings (STRIPE_SECRET_KEY,
  STRIPE_WEBHOOK_SECRET) at call time. Nothing is hard-coded or logged.
* Live keys (sk_live_/rk_live_) are refused unless STRIPE_ALLOW_LIVE is set.
* Uses the Stripe REST API through httpx (already a dependency) rather than
  adding the stripe SDK; the transport is injectable for tests.
* Signature verification ports verify_stripe_signature from
  veklom_billing_orchestrator.py, adding timestamp tolerance, multiple v1
  signatures and constant-time comparison.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import time
from datetime import datetime
from typing import Any
from urllib.parse import urlencode

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.config.settings import settings
from core.entitlements import plans as P
from core.entitlements import service as S
from core.entitlements.activation import emit_activation_event
from core.entitlements.config import get_entitlement_settings
from db.models import StripeWebhookEvent, Workspace

# kind -> Stripe price lookup_key (created by scripts/stripe_setup.py)
LOOKUP_KEYS: dict[str, str] = {
    "pro": "veklom_pro_monthly",
    "team": "veklom_team_monthly",
    "topup_50": "veklom_topup_50",
    "topup_100": "veklom_topup_100",
    "topup_500": "veklom_topup_500",
}
SUBSCRIPTION_KINDS = {"pro": P.PRO, "team": P.TEAM}
TOPUP_USD = {"topup_50": 50, "topup_100": 100, "topup_500": 500}
PLAN_BY_LOOKUP = {LOOKUP_KEYS[k]: plan for k, plan in SUBSCRIPTION_KINDS.items()}
DOWNGRADE_STATUSES = {"canceled", "unpaid", "incomplete_expired"}


class StripeConfigError(RuntimeError):
    pass


class StripeSignatureError(ValueError):
    pass


def topup_credits(kind: str) -> int:
    return TOPUP_USD[kind] * get_entitlement_settings().TOPUP_CREDITS_PER_USD


def assert_test_key(key: str, *, allow_live: bool = False) -> None:
    if not key:
        raise StripeConfigError("STRIPE_SECRET_KEY is not configured")
    if key.startswith(("sk_live_", "rk_live_")) and not allow_live:
        raise StripeConfigError("refusing to use a live Stripe key (test mode only)")
    if not key.startswith(("sk_test_", "rk_test_", "sk_live_", "rk_live_")):
        raise StripeConfigError("STRIPE_SECRET_KEY is not a Stripe secret key")


def _flatten(data: Any, prefix: str = "") -> list[tuple[str, str]]:
    """Stripe form encoding: a[b][0][c]=v."""
    out: list[tuple[str, str]] = []
    if isinstance(data, dict):
        for k, v in data.items():
            out += _flatten(v, f"{prefix}[{k}]" if prefix else str(k))
    elif isinstance(data, (list, tuple)):
        for i, v in enumerate(data):
            out += _flatten(v, f"{prefix}[{i}]")
    elif isinstance(data, bool):
        out.append((prefix, "true" if data else "false"))
    elif data is not None:
        out.append((prefix, str(data)))
    return out


class StripeClient:
    def __init__(self, secret_key: str, *, api_base: str | None = None,
                 transport: httpx.BaseTransport | None = None, allow_live: bool = False) -> None:
        assert_test_key(secret_key, allow_live=allow_live)
        self._key = secret_key
        self._base = (api_base or get_entitlement_settings().STRIPE_API_BASE).rstrip("/")
        self._transport = transport

    def request(self, method: str, path: str, data: dict | None = None, *,
                params: list[tuple[str, str]] | None = None, idempotency_key: str | None = None) -> dict:
        headers = {"Authorization": f"Bearer {self._key}"}
        if idempotency_key:
            headers["Idempotency-Key"] = idempotency_key
        form = _flatten(data or {})
        content = None
        if form:
            content = urlencode(form).encode()
            headers["Content-Type"] = "application/x-www-form-urlencoded"
        with httpx.Client(transport=self._transport, timeout=20.0) as client:
            resp = client.request(method, f"{self._base}{path}", headers=headers,
                                  content=content, params=params)
        body = resp.json() if resp.content else {}
        if resp.status_code >= 400:
            err = body.get("error", {}) if isinstance(body, dict) else {}
            raise httpx.HTTPStatusError(
                f"stripe {method} {path} -> {resp.status_code} {err.get('type', '')}",
                request=resp.request, response=resp)
        return body

    def price_for_lookup_key(self, lookup_key: str) -> dict | None:
        res = self.request("GET", "/v1/prices", params=[("lookup_keys[]", lookup_key), ("active", "true"), ("limit", "1")])
        data = res.get("data") or []
        return data[0] if data else None


def default_client() -> StripeClient:
    cfg = get_entitlement_settings()
    return StripeClient(settings.STRIPE_SECRET_KEY, allow_live=cfg.STRIPE_ALLOW_LIVE)


# Swappable in tests.
client_factory = default_client


def verify_signature(payload: bytes, sig_header: str | None, secret: str, *,
                     tolerance: int | None = None, now: float | None = None) -> dict:
    if not secret:
        raise StripeConfigError("STRIPE_WEBHOOK_SECRET is not configured")
    if not sig_header:
        raise StripeSignatureError("missing Stripe-Signature header")
    parts = [p.strip().split("=", 1) for p in sig_header.split(",") if "=" in p]
    timestamp = next((v for k, v in parts if k == "t"), None)
    signatures = [v for k, v in parts if k == "v1"]
    if not timestamp or not signatures:
        raise StripeSignatureError("malformed Stripe-Signature header")
    expected = hmac.new(secret.encode(), f"{timestamp}.".encode() + payload, hashlib.sha256).hexdigest()
    if not any(hmac.compare_digest(expected, s) for s in signatures):
        raise StripeSignatureError("signature mismatch")
    tol = get_entitlement_settings().STRIPE_WEBHOOK_TOLERANCE_SECONDS if tolerance is None else tolerance
    if abs((now or time.time()) - int(timestamp)) > tol:
        raise StripeSignatureError("timestamp outside tolerance")
    return json.loads(payload)


def sign_payload(payload: bytes, secret: str, timestamp: int | None = None) -> str:
    """Build a Stripe-Signature header (used by tests and local tooling)."""
    ts = int(timestamp or time.time())
    sig = hmac.new(secret.encode(), f"{ts}.".encode() + payload, hashlib.sha256).hexdigest()
    return f"t={ts},v1={sig}"


# ---------------------------------------------------------------------------
# Checkout / portal
# ---------------------------------------------------------------------------


def create_checkout_session(client: StripeClient, *, workspace: Workspace, email: str, kind: str) -> dict:
    if kind not in LOOKUP_KEYS:
        raise ValueError("unknown checkout kind")
    price = client.price_for_lookup_key(LOOKUP_KEYS[kind])
    if price is None:
        raise StripeConfigError(f"price {LOOKUP_KEYS[kind]} not found; run scripts/stripe_setup.py")
    front = settings.FRONTEND_URL.rstrip("/")
    metadata = {"workspace_id": workspace.id, "kind": kind}
    params: dict[str, Any] = {
        "line_items": [{"price": price["id"], "quantity": 1}],
        "client_reference_id": workspace.id,
        "success_url": f"{front}/os?checkout=success&session_id={{CHECKOUT_SESSION_ID}}",
        "cancel_url": f"{front}/os?checkout=cancelled",
    }
    if kind in SUBSCRIPTION_KINDS:
        params["mode"] = "subscription"
        params["subscription_data"] = {"metadata": metadata}
    else:
        credits = int((price.get("metadata") or {}).get("credits") or topup_credits(kind))
        metadata["credits"] = str(credits)
        params["mode"] = "payment"
        params["payment_intent_data"] = {"metadata": metadata}
    params["metadata"] = metadata
    if workspace.stripe_customer_id:
        params["customer"] = workspace.stripe_customer_id
    else:
        params["customer_email"] = email
    session = client.request("POST", "/v1/checkout/sessions", params)
    return {"id": session.get("id"), "url": session.get("url"), "kind": kind, "mode": params["mode"]}


def create_portal_session(client: StripeClient, *, workspace: Workspace) -> dict:
    if not workspace.stripe_customer_id:
        raise ValueError("workspace has no Stripe customer")
    front = settings.FRONTEND_URL.rstrip("/")
    portal = client.request("POST", "/v1/billing_portal/sessions",
                            {"customer": workspace.stripe_customer_id, "return_url": f"{front}/os"})
    return {"url": portal.get("url")}


# ---------------------------------------------------------------------------
# Webhook processing
# ---------------------------------------------------------------------------


async def _workspace_for(db: AsyncSession, obj: dict) -> Workspace | None:
    meta = obj.get("metadata") or {}
    parent = ((obj.get("parent") or {}).get("subscription_details") or {}).get("metadata") or {}
    sub_details = (obj.get("subscription_details") or {}).get("metadata") or {}
    for ws_id in (meta.get("workspace_id"), obj.get("client_reference_id"),
                  parent.get("workspace_id"), sub_details.get("workspace_id")):
        if ws_id:
            ws = await db.get(Workspace, ws_id)
            if ws:
                return ws
    sub_id = obj.get("subscription") if isinstance(obj.get("subscription"), str) else None
    if obj.get("object") == "subscription":
        sub_id = obj.get("id")
    if sub_id:
        ws = (await db.execute(select(Workspace).where(Workspace.stripe_subscription_id == sub_id))).scalars().first()
        if ws:
            return ws
    customer = obj.get("customer") if isinstance(obj.get("customer"), str) else None
    if customer:
        return (await db.execute(select(Workspace).where(Workspace.stripe_customer_id == customer))).scalars().first()
    return None


def _subscription_plan(sub: dict) -> str | None:
    for item in ((sub.get("items") or {}).get("data") or []):
        plan = PLAN_BY_LOOKUP.get(((item.get("price") or {}).get("lookup_key")) or "")
        if plan:
            return plan
    kind = (sub.get("metadata") or {}).get("kind")
    return SUBSCRIPTION_KINDS.get(kind or "")


async def _handle(db: AsyncSession, event: dict, now: datetime) -> tuple[str | None, str]:
    etype = event.get("type")
    obj = (event.get("data") or {}).get("object") or {}
    ws = await _workspace_for(db, obj)
    if ws is None:
        return None, "workspace_not_found"
    ws_id = ws.id

    if etype == "checkout.session.completed":
        meta = obj.get("metadata") or {}
        kind = meta.get("kind")
        if isinstance(obj.get("customer"), str):
            ws.stripe_customer_id = obj["customer"]
        if obj.get("mode") == "subscription" and kind in SUBSCRIPTION_KINDS:
            if obj.get("payment_status") not in ("paid", "no_payment_required"):
                await db.commit()
                return ws_id, "subscription_not_paid"
            if isinstance(obj.get("subscription"), str):
                ws.stripe_subscription_id = obj["subscription"]
            ws.subscription_status = "active"
            await db.commit()
            await S.set_plan(db, ws_id, SUBSCRIPTION_KINDS[kind], now=now)
            result = f"plan_set:{SUBSCRIPTION_KINDS[kind]}"
        elif obj.get("mode") == "payment" and kind in TOPUP_USD:
            if obj.get("payment_status") != "paid":
                await db.commit()
                return ws_id, "payment_not_paid"
            await db.commit()
            credits = int(meta.get("credits") or topup_credits(kind))
            await S.grant_topup(db, ws_id, credits, idempotency_key=f"stripe:checkout:{obj.get('id')}",
                                settlement_rail="stripe_fiat",
                                settlement_ref=obj.get("payment_intent") or obj.get("id"), now=now)
            result = f"topup:{credits}"
        else:
            await db.commit()
            return ws_id, "ignored_checkout_kind"
        await emit_activation_event(db, "funding_method_added", workspace_id=ws_id, ref="stripe",
                                    details={"kind": kind})
        return ws_id, result

    if etype in ("customer.subscription.updated", "customer.subscription.deleted"):
        status = obj.get("status")
        if etype == "customer.subscription.deleted" or status in DOWNGRADE_STATUSES:
            ws.subscription_status = "canceled" if etype == "customer.subscription.deleted" else status
            await db.commit()
            await S.set_plan(db, ws_id, P.DEVELOPER, now=now)
            return ws_id, "downgraded:developer"
        if status == "past_due":
            ws.subscription_status = "past_due"
            await db.commit()
            return ws_id, "past_due"
        ws.subscription_status = status or ws.subscription_status
        ws.stripe_subscription_id = obj.get("id") or ws.stripe_subscription_id
        await db.commit()
        plan = _subscription_plan(obj)
        ent = await S._load(db, ws_id, lock=False)
        if plan and ent is not None and ent.plan != plan and status in ("active", "trialing"):
            await S.set_plan(db, ws_id, plan, now=now)
            return ws_id, f"plan_changed:{plan}"
        return ws_id, f"status:{status}"

    if etype == "invoice.paid":
        if obj.get("billing_reason") != "subscription_cycle":
            return ws_id, "ignored_non_cycle_invoice"
        ws.subscription_status = "active"
        await db.commit()
        await S.renew_period(db, ws_id, ref=f"stripe:invoice:{obj.get('id')}", now=now)
        return ws_id, "allowance_reset"

    if etype == "invoice.payment_failed":
        ws.subscription_status = "past_due"  # no instant downgrade
        await db.commit()
        return ws_id, "past_due"

    return ws_id, "ignored_event_type"


async def process_event(db: AsyncSession, event: dict, *, now: datetime | None = None) -> dict:
    """Idempotent by Stripe event id: a processed event is never applied twice."""
    now = now or datetime.utcnow()
    event_id = event.get("id")
    if not event_id:
        raise StripeSignatureError("event without id")
    row = await db.get(StripeWebhookEvent, event_id)
    if row is not None and row.status == "processed":
        return {"duplicate": True, "result": row.result}
    if row is None:
        row = StripeWebhookEvent(event_id=event_id, event_type=str(event.get("type")),
                                 status="processing", created_at=now)
        db.add(row)
    else:
        row.status = "processing"
    await db.commit()
    try:
        ws_id, result = await _handle(db, event, now)
    except Exception:
        await db.rollback()
        failed = await db.get(StripeWebhookEvent, event_id)
        if failed is not None:
            failed.status = "failed"
            await db.commit()
        raise
    row = await db.get(StripeWebhookEvent, event_id)
    row.status = "processed"
    row.workspace_id = ws_id
    row.result = result
    row.processed_at = datetime.utcnow()
    await db.commit()
    return {"duplicate": False, "result": result}
