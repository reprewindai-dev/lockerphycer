"""Workspace management routes."""

from datetime import datetime
from typing import Optional
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from core.database.database import get_db
from core.security.auth import get_current_user, require_admin
from db.models import MarketplaceListing, SubscriptionTier, User, Workspace

router = APIRouter()


class WorkspaceCreateRequest(BaseModel):
    """User-owned workspace creation contract used during onboarding."""

    name: str = Field(min_length=1, max_length=160)
    slug: Optional[str] = Field(default=None, min_length=1, max_length=180)


def _normalize_slug(value: str) -> str:
    normalized = "-".join(value.strip().lower().replace("_", "-").split())
    normalized = "".join(ch for ch in normalized if ch.isalnum() or ch == "-")
    normalized = normalized.strip("-")
    if not normalized:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Workspace slug is empty after normalization")
    return normalized[:180]


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
    payload: WorkspaceCreateRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Create or return the authenticated user's onboarding workspace.

    Workspace creation is an identity operation, not an administrator-only
    control-plane mutation. The route is deliberately idempotent for the
    authenticated owner so a machine or browser may safely retry onboarding.
    """

    existing_result = await db.execute(
        select(Workspace).where(
            Workspace.owner_id == current_user.email,
            Workspace.is_active == True,
        ).order_by(Workspace.created_at.asc())
    )
    existing = existing_result.scalars().first()
    if existing:
        return {
            "id": existing.id,
            "name": existing.name,
            "slug": existing.slug,
            "tier": existing.tier.value if existing.tier else "free",
            "existing": True,
        }

    slug = _normalize_slug(payload.slug or payload.name)
    slug_owner = (await db.execute(select(Workspace).where(Workspace.slug == slug))).scalars().first()
    if slug_owner:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Workspace slug already exists")

    ws = Workspace(
        id=str(uuid4()),
        owner_id=current_user.email,
        name=payload.name.strip(),
        slug=slug,
        tier=SubscriptionTier.FREE,
    )
    db.add(ws)
    await db.commit()
    await db.refresh(ws)
    return {
        "id": ws.id,
        "name": ws.name,
        "slug": ws.slug,
        "tier": ws.tier.value,
        "existing": False,
    }


@router.get("/{workspace_id}")
async def get_workspace(
    workspace_id: str,
    admin_email: str = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
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
