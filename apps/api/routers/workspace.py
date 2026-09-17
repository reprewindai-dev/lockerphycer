"""Workspace management routes"""

from datetime import datetime
from typing import Optional
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from core.database.database import get_db
from core.security.auth import get_current_user, require_admin
from db.models import MarketplaceListing, SubscriptionTier, User, Workspace

router = APIRouter()


@router.get("/")
async def list_workspaces(
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    admin_email: str = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(Workspace).where(Workspace.is_active == True).offset(skip).limit(limit))
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
    admin_email: str = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    ws = Workspace(
        id=str(uuid4()),
        owner_id=admin_email,
        name=name,
        slug=slug or name.lower().replace(" ", "-"),
        tier=SubscriptionTier.FREE,
    )
    db.add(ws)
    await db.commit()
    await db.refresh(ws)
    return {"id": ws.id, "name": ws.name, "slug": ws.slug, "tier": ws.tier.value}


@router.get("/{workspace_id}")
async def get_workspace(workspace_id: str, admin_email: str = Depends(require_admin), db: AsyncSession = Depends(get_db)):
    ws = await db.get(Workspace, workspace_id)
    if not ws:
        raise HTTPException(status_code=404, detail="Workspace not found")
    listing_count = await db.execute(
        select(func.count()).select_from(MarketplaceListing).where(MarketplaceListing.workspace_id == workspace_id)
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


@router.get("/{workspace_id}/vlink-authorization")
async def authorize_vlink_workspace(
    workspace_id: str,
    response: Response,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Confirm that the authenticated session owns an active workspace.

    This deliberately does not inherit the administrative workspace read path:
    VLink creation needs an owner-bound authorization decision, not permission
    to inspect arbitrary workspaces.
    """
    ws = await db.get(Workspace, workspace_id)
    if not ws or not ws.is_active:
        raise HTTPException(status_code=404, detail="Active workspace not found")
    if ws.owner_id != current_user.email:
        raise HTTPException(status_code=403, detail="Workspace ownership required")
    response.headers["Cache-Control"] = "no-store"
    response.headers["Vary"] = "Authorization"
    return {
        "authorized": True,
        "workspace_id": ws.id,
    }


@router.put("/{workspace_id}")
async def update_workspace(
    workspace_id: str,
    name: Optional[str] = None,
    tier: Optional[str] = None,
    admin_email: str = Depends(require_admin),
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
async def deactivate_workspace(
    workspace_id: str,
    admin_email: str = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    ws = await db.get(Workspace, workspace_id)
    if not ws:
        raise HTTPException(status_code=404, detail="Workspace not found")
    ws.is_active = False
    await db.commit()
    return {"message": "Workspace deactivated"}
