"""Workspace management routes."""

from datetime import datetime, timedelta
from typing import Optional
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from fastapi.responses import JSONResponse
from fastapi.security import HTTPAuthorizationCredentials
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from core.config.settings import settings
from core.database.database import get_db
from core.security.auth import (
    bearer,
    create_access_token,
    create_refresh_token,
    get_current_user,
    require_admin,
)
from db.models import MarketplaceListing, SubscriptionTier, User, UserSession, Workspace

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


async def _bind_session_to_workspace(
    *,
    db: AsyncSession,
    user: User,
    credentials: HTTPAuthorizationCredentials,
    workspace: Workspace,
) -> dict[str, str]:
    """Rotate the authenticated session so CAPPO receives the real workspace claim."""

    session = (
        await db.execute(
            select(UserSession).where(
                UserSession.session_token == credentials.credentials,
                UserSession.user_id == user.id,
                UserSession.is_active == True,
            )
        )
    ).scalars().first()
    if not session:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Session revoked or expired")

    claims = {"sub": user.email, "workspace_id": workspace.id}
    access_token = create_access_token(claims)
    refresh_token = create_refresh_token(claims)
    now = datetime.utcnow()
    session.session_token = access_token
    session.refresh_token = refresh_token
    session.last_accessed = now
    session.expires_at = now + timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS)
    await db.commit()
    return {
        "access_token": access_token,
        "refresh_token": refresh_token,
        "token_type": "bearer",
    }


async def _workspace_payload(
    *,
    db: AsyncSession,
    user: User,
    credentials: HTTPAuthorizationCredentials,
    workspace: Workspace,
    existing: bool,
) -> dict:
    tokens = await _bind_session_to_workspace(
        db=db,
        user=user,
        credentials=credentials,
        workspace=workspace,
    )
    return {
        "id": workspace.id,
        "name": workspace.name,
        "slug": workspace.slug,
        "tier": workspace.tier.value if workspace.tier else "free",
        "existing": existing,
        **tokens,
    }


@router.get("")
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


@router.post("")
@router.post("/")
async def create_workspace(
    payload: WorkspaceCreateRequest,
    current_user: User = Depends(get_current_user),
    credentials: HTTPAuthorizationCredentials = Depends(bearer),
    db: AsyncSession = Depends(get_db),
):
    """Create/return the user's workspace and rotate the session onto that identity.

    Authentication establishes the operator. This step establishes the workspace
    context CAPPO later consumes. It remains separate from consequence authority:
    the returned token carries workspace identity but grants no capability mount.
    """

    existing_result = await db.execute(
        select(Workspace).where(
            Workspace.owner_id == current_user.email,
            Workspace.is_active == True,
        ).order_by(Workspace.created_at.asc())
    )
    existing = existing_result.scalars().first()
    if existing:
        return await _workspace_payload(
            db=db,
            user=current_user,
            credentials=credentials,
            workspace=existing,
            existing=True,
        )

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
    await db.flush()
    await db.refresh(ws)
    return await _workspace_payload(
        db=db,
        user=current_user,
        credentials=credentials,
        workspace=ws,
        existing=False,
    )


@router.get("/me")
async def get_my_workspace(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(Workspace)
        .where(
            Workspace.owner_id == current_user.email,
            Workspace.is_active == True,
        )
        .order_by(Workspace.created_at.asc())
    )
    workspace = result.scalars().first()
    if not workspace:
        return JSONResponse(
            status_code=404,
            content={"detail": "No workspace bound to this operator"},
        )
    return {
        "id": workspace.id,
        "name": workspace.name,
        "slug": workspace.slug,
        "tier": workspace.tier.value if workspace.tier else "free",
        "is_active": workspace.is_active,
        "created_at": workspace.created_at.isoformat() if workspace.created_at else None,
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


@router.get("/{workspace_id}/vlink-authorization")
async def authorize_vlink_workspace(
    workspace_id: str,
    response: Response,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Confirm that the authenticated session owns an active workspace."""
    ws = await db.get(Workspace, workspace_id)
    if not ws or not ws.is_active:
        raise HTTPException(status_code=404, detail="Active workspace not found")
    if ws.owner_id != current_user.email:
        raise HTTPException(status_code=403, detail="Workspace ownership required")
    response.headers["Cache-Control"] = "no-store"
    response.headers["Vary"] = "Authorization"
    return {"authorized": True, "workspace_id": ws.id}


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
