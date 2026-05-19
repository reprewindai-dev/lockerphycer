"""Workspace management routes"""

from fastapi import APIRouter, Depends, HTTPException, status, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from typing import Optional
from datetime import datetime
import uuid

from core.database.database import get_db
from db.models import Workspace, User, SubscriptionTier, MarketplaceListing

router = APIRouter()


@router.get("/")
async def list_workspaces(
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(Workspace).where(Workspace.is_active == True).offset(skip).limit(limit)
    )
    workspaces = result.scalars().all()
    return [
        {
            "id": w.id,
            "name": w.name,
            "slug": w.slug,
            "tier": w.tier.value if w.tier else "free",
            "is_active": w.is_active,
            "created_at": w.created_at.isoformat() if w.created_at else None,
        }
        for w in workspaces
    ]


@router.post("/")
async def create_workspace(
    name: str,
    slug: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
):
    ws = Workspace(
        id=str(uuid.uuid4()),
        owner_id="system",
        name=name,
        slug=slug or name.lower().replace(" ", "-"),
        tier=SubscriptionTier.FREE,
    )
    db.add(ws)
    await db.commit()
    await db.refresh(ws)
    return {"id": ws.id, "name": ws.name, "slug": ws.slug, "tier": ws.tier.value}


@router.get("/{workspace_id}")
async def get_workspace(workspace_id: str, db: AsyncSession = Depends(get_db)):
    ws = await db.get(Workspace, workspace_id)
    if not ws:
        raise HTTPException(status_code=404, detail="Workspace not found")
    listing_count = await db.execute(
        select(func.count()).select_from(MarketplaceListing).where(
            MarketplaceListing.workspace_id == workspace_id
        )
    )
    return {
        "id": ws.id,
        "name": ws.name,
        "slug": ws.slug,
        "tier": ws.tier.value if ws.tier else "free",
        "is_active": ws.is_active,
        "settings": ws.settings,
        "listing_count": listing_count.scalar() or 0,
        "created_at": ws.created_at.isoformat() if ws.created_at else None,
    }


@router.put("/{workspace_id}")
async def update_workspace(
    workspace_id: str,
    name: Optional[str] = None,
    tier: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
):
    ws = await db.get(Workspace, workspace_id)
    if not ws:
        raise HTTPException(status_code=404, detail="Workspace not found")
    if name:
        ws.name = name
    if tier:
        ws.tier = SubscriptionTier(tier)
    ws.updated_at = datetime.utcnow()
    await db.commit()
    return {"id": ws.id, "name": ws.name, "tier": ws.tier.value}


@router.delete("/{workspace_id}")
async def deactivate_workspace(workspace_id: str, db: AsyncSession = Depends(get_db)):
    ws = await db.get(Workspace, workspace_id)
    if not ws:
        raise HTTPException(status_code=404, detail="Workspace not found")
    ws.is_active = False
    await db.commit()
    return {"message": "Workspace deactivated"}
