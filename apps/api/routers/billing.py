"""Billing, wallet, and subscription routes"""

import asyncio
from datetime import datetime
from typing import Optional
from uuid import uuid4

import httpx
from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request
from fastapi.security import HTTPAuthorizationCredentials
from pydantic import BaseModel, Field
from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.routers.entitlements import _current_workspace
from core.config.settings import settings as app_settings
from core.database.database import get_db
from core.entitlements import stripe_billing
from core.security.auth import bearer, get_current_user, require_admin
from db.models import SubscriptionTier, User, WalletTransaction, Workspace

router = APIRouter()

PRICING = {
    "free": {"activation": 0, "min_reserve": 0, "playground_run": 0},
    "founding": {
        "activation": 39500,
        "min_reserve": 15000,
        "playground_run": 25,
        "compare_run": 75,
        "uacp_compile": 150,
        "pipeline_test": 25,
        "endpoint_test": 50,
        "byok_gov_per_k": 600,
        "managed_gov_per_k": 1200,
    },
    "standard": {
        "activation": 79500,
        "min_reserve": 30000,
        "playground_run": 40,
        "compare_run": 120,
        "uacp_compile": 200,
        "pipeline_test": 40,
        "endpoint_test": 80,
        "byok_gov_per_k": 800,
        "managed_gov_per_k": 1600,
    },
    "regulated": {
        "activation": 250000,
        "min_reserve": 250000,
        "byok_gov_per_k": 1000,
        "managed_gov_per_k": 2000,
    },
    "managed_service": {
        "base_managed_ops_monthly": 150000,
        "per_environment_after_first": 50000,
        "per_cluster": 75000,
        "per_node": 6500,
        "regulated_workload_addon": 125000,
        "air_gapped_addon": 300000,
        "minimum_onboarding": 500000,
    },
}


@router.get("/pricing")
async def get_pricing():
    return PRICING


@router.get("/wallet/{workspace_id}")
async def get_wallet(workspace_id: str, admin_email: str = Depends(require_admin), db: AsyncSession = Depends(get_db)):
    ws = await db.get(Workspace, workspace_id)
    if not ws:
        raise HTTPException(status_code=404, detail="Workspace not found")
    last_tx = await db.execute(
        select(WalletTransaction)
        .where(WalletTransaction.workspace_id == workspace_id)
        .order_by(desc(WalletTransaction.created_at))
        .limit(1)
    )
    tx = last_tx.scalars().first()
    balance = tx.balance_after_cents if tx else 0
    return {"workspace_id": workspace_id, "balance_cents": balance, "tier": ws.tier.value if ws.tier else "free"}


@router.get("/wallet/{workspace_id}/transactions")
async def list_transactions(
    workspace_id: str,
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    admin_email: str = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(WalletTransaction)
        .where(WalletTransaction.workspace_id == workspace_id)
        .order_by(desc(WalletTransaction.created_at))
        .offset(skip)
        .limit(limit)
    )
    txs = result.scalars().all()
    return [
        {
            "id": t.id,
            "amount_cents": t.amount_cents,
            "balance_after_cents": t.balance_after_cents,
            "event_type": t.event_type,
            "description": t.description,
            "created_at": t.created_at.isoformat() if t.created_at else None,
        }
        for t in txs
    ]


@router.post("/wallet/{workspace_id}/fund")
async def fund_wallet(
    workspace_id: str,
    amount_cents: int,
    admin_email: str = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    ws = await db.get(Workspace, workspace_id)
    if not ws:
        raise HTTPException(status_code=404, detail="Workspace not found")
    if amount_cents <= 0:
        raise HTTPException(status_code=400, detail="amount_cents must be positive")
    last_tx = await db.execute(
        select(WalletTransaction)
        .where(WalletTransaction.workspace_id == workspace_id)
        .order_by(desc(WalletTransaction.created_at))
        .limit(1)
    )
    prev = last_tx.scalars().first()
    balance = (prev.balance_after_cents if prev else 0) + amount_cents
    tx = WalletTransaction(
        id=str(uuid4()),
        workspace_id=workspace_id,
        amount_cents=amount_cents,
        balance_after_cents=balance,
        event_type="fund",
        description=f"Wallet funded +${amount_cents / 100:.2f}",
    )
    db.add(tx)
    await db.commit()
    return {"balance_cents": balance, "transaction_id": tx.id}


# ---------------------------------------------------------------------------
# Stripe (TEST mode): checkout, customer portal, webhook
# ---------------------------------------------------------------------------


class CheckoutRequest(BaseModel):
    kind: str = Field(pattern=r"^(pro|team|topup_50|topup_100|topup_500)$")


@router.post("/checkout")
async def create_checkout(
    body: CheckoutRequest,
    current_user: User = Depends(get_current_user),
    credentials: HTTPAuthorizationCredentials = Depends(bearer),
    db: AsyncSession = Depends(get_db),
):
    ws = await _current_workspace(db, current_user, credentials)
    if (
        body.kind in stripe_billing.SUBSCRIPTION_KINDS
        and ws.stripe_subscription_id
        and ws.subscription_status in ("active", "trialing", "past_due")
    ):
        raise HTTPException(status_code=409, detail="Subscription exists; use the billing portal to change it")
    try:
        client = stripe_billing.client_factory()
        return await asyncio.to_thread(
            stripe_billing.create_checkout_session, client,
            workspace=ws, email=current_user.email, kind=body.kind,
        )
    except stripe_billing.StripeConfigError as exc:
        raise HTTPException(status_code=503, detail="Stripe is not configured") from exc
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=502, detail="Stripe request failed") from exc


@router.post("/portal")
async def create_portal(
    current_user: User = Depends(get_current_user),
    credentials: HTTPAuthorizationCredentials = Depends(bearer),
    db: AsyncSession = Depends(get_db),
):
    ws = await _current_workspace(db, current_user, credentials)
    if not ws.stripe_customer_id:
        raise HTTPException(status_code=404, detail="No Stripe customer for this workspace")
    try:
        client = stripe_billing.client_factory()
        return await asyncio.to_thread(stripe_billing.create_portal_session, client, workspace=ws)
    except stripe_billing.StripeConfigError as exc:
        raise HTTPException(status_code=503, detail="Stripe is not configured") from exc
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=502, detail="Stripe request failed") from exc


@router.post("/stripe/webhook")
async def stripe_webhook(
    request: Request,
    stripe_signature: Optional[str] = Header(default=None, alias="Stripe-Signature"),
    db: AsyncSession = Depends(get_db),
):
    payload = await request.body()
    try:
        event = stripe_billing.verify_signature(payload, stripe_signature, app_settings.STRIPE_WEBHOOK_SECRET)
    except stripe_billing.StripeConfigError as exc:
        raise HTTPException(status_code=503, detail="Stripe webhook secret not configured") from exc
    except (stripe_billing.StripeSignatureError, ValueError) as exc:
        raise HTTPException(status_code=400, detail="Invalid Stripe signature") from exc
    result = await stripe_billing.process_event(db, event)
    return {"received": True, **result}


@router.post("/activate/{workspace_id}")
async def activate_workspace(
    workspace_id: str,
    tier: str = "founding",
    admin_email: str = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    ws = await db.get(Workspace, workspace_id)
    if not ws:
        raise HTTPException(status_code=404, detail="Workspace not found")
    if tier not in PRICING:
        raise HTTPException(status_code=400, detail="Invalid tier")
    ws.tier = SubscriptionTier(tier)
    ws.updated_at = datetime.utcnow()
    await db.commit()
    return {"workspace_id": workspace_id, "tier": tier, "activated": True}
