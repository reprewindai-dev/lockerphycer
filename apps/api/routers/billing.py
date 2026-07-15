"""Billing, wallet, and subscription routes"""

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, desc
from typing import Optional
from datetime import datetime
import uuid

from core.database.database import get_db
from db.models import WalletTransaction, Workspace, SubscriptionTier

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
async def get_wallet(workspace_id: str, db: AsyncSession = Depends(get_db)):
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
    return {
        "workspace_id": workspace_id,
        "balance_cents": balance,
        "tier": ws.tier.value if ws.tier else "free",
    }


@router.get("/wallet/{workspace_id}/transactions")
async def list_transactions(
    workspace_id: str,
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
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
    db: AsyncSession = Depends(get_db),
):
    ws = await db.get(Workspace, workspace_id)
    if not ws:
        raise HTTPException(status_code=404, detail="Workspace not found")
    last_tx = await db.execute(
        select(WalletTransaction)
        .where(WalletTransaction.workspace_id == workspace_id)
        .order_by(desc(WalletTransaction.created_at))
        .limit(1)
    )
    prev = last_tx.scalars().first()
    balance = (prev.balance_after_cents if prev else 0) + amount_cents
    tx = WalletTransaction(
        id=str(uuid.uuid4()),
        workspace_id=workspace_id,
        amount_cents=amount_cents,
        balance_after_cents=balance,
        event_type="fund",
        description=f"Wallet funded +${amount_cents / 100:.2f}",
    )
    db.add(tx)
    await db.commit()
    return {"balance_cents": balance, "transaction_id": tx.id}


@router.post("/activate/{workspace_id}")
async def activate_workspace(
    workspace_id: str,
    tier: str = "founding",
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
