from typing import List, Optional
from datetime import datetime, timedelta
import secrets
import hashlib
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from fastapi.responses import JSONResponse
from sqlalchemy import func, or_, select

from core.database.database import get_db
from core.entitlements.service import EntitlementError, check_agent_limit
from core.security.auth import get_current_user, create_access_token
from db.models import User, Workspace, MachineToken

router = APIRouter(prefix="/machine-tokens", tags=["Machine Tokens"])

class MachineTokenCreateRequest(BaseModel):
    name: str
    workspace_id: str
    expires_in_days: int = 30

class MachineTokenCreateResponse(BaseModel):
    id: str
    name: str
    secret: str
    workspace_id: str
    expires_at: datetime

class MachineTokenListResponse(BaseModel):
    id: str
    name: str
    workspace_id: str
    status: str
    created_at: datetime
    expires_at: Optional[datetime]

class MachineExchangeRequest(BaseModel):
    pass # No body, token comes from Authorization header

class MachineExchangeResponse(BaseModel):
    access_token: str
    token_type: str
    workspace_id: str

def _hash_secret(secret: str) -> str:
    return hashlib.sha256(secret.encode()).hexdigest()

@router.post("", response_model=MachineTokenCreateResponse)
@router.post("/", response_model=MachineTokenCreateResponse)
async def create_machine_token(
    payload: MachineTokenCreateRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    ws = await db.get(Workspace, payload.workspace_id)
    if not ws or ws.owner_id != current_user.email or not ws.is_active:
        raise HTTPException(status_code=403, detail="Workspace ownership required")

    # Plan agent limit: an active machine token is the workspace's agent credential.
    now = datetime.utcnow()
    active_agents = (
        await db.execute(
            select(func.count()).select_from(MachineToken).where(
                MachineToken.workspace_id == ws.id,
                MachineToken.status == "active",
                MachineToken.revoked_at.is_(None),
                or_(MachineToken.expires_at.is_(None), MachineToken.expires_at > now),
            )
        )
    ).scalar_one()
    try:
        await check_agent_limit(db, ws, int(active_agents))
    except EntitlementError as exc:
        await db.commit()  # keep the lazily-created entitlement row
        return JSONResponse(status_code=exc.status_code, content={"error": exc.body})

    raw_secret = f"vkl_live_{secrets.token_urlsafe(32)}"
    hashed = _hash_secret(raw_secret)
    expires = datetime.utcnow() + timedelta(days=payload.expires_in_days)

    token = MachineToken(
        hashed_secret=hashed,
        workspace_id=payload.workspace_id,
        created_by=current_user.email,
        name=payload.name,
        expires_at=expires
    )
    db.add(token)
    await db.commit()
    await db.refresh(token)

    return MachineTokenCreateResponse(
        id=token.id,
        name=token.name,
        secret=raw_secret,
        workspace_id=token.workspace_id,
        expires_at=token.expires_at
    )

@router.get("", response_model=List[MachineTokenListResponse])
@router.get("/", response_model=List[MachineTokenListResponse])
async def list_machine_tokens(
    workspace_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    ws = await db.get(Workspace, workspace_id)
    if not ws or ws.owner_id != current_user.email:
        raise HTTPException(status_code=403, detail="Workspace ownership required")

    result = await db.execute(select(MachineToken).where(MachineToken.workspace_id == workspace_id).order_by(MachineToken.created_at.desc()))
    tokens = result.scalars().all()
    
    return [
        MachineTokenListResponse(
            id=t.id,
            name=t.name,
            workspace_id=t.workspace_id,
            status=t.status,
            created_at=t.created_at,
            expires_at=t.expires_at
        ) for t in tokens
    ]

@router.delete("/{token_id}")
async def revoke_machine_token(
    token_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    token = await db.get(MachineToken, token_id)
    if not token:
        raise HTTPException(status_code=404, detail="Token not found")
        
    ws = await db.get(Workspace, token.workspace_id)
    if not ws or ws.owner_id != current_user.email:
        raise HTTPException(status_code=403, detail="Workspace ownership required")

    token.status = "revoked"
    token.revoked_at = datetime.utcnow()
    await db.commit()
    return {"detail": "Token revoked"}

from fastapi import Request

@router.post("/exchange", response_model=MachineExchangeResponse)
async def exchange_machine_token(
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    auth_header = request.headers.get("Authorization")
    if not auth_header or not auth_header.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing Bearer token")
        
    raw_secret = auth_header.split(" ")[1]
    hashed = _hash_secret(raw_secret)
    
    result = await db.execute(select(MachineToken).where(MachineToken.hashed_secret == hashed, MachineToken.status == "active"))
    token = result.scalars().first()
    
    if not token:
        raise HTTPException(status_code=401, detail="Invalid or revoked machine token")
        
    if token.expires_at and token.expires_at < datetime.utcnow():
        token.status = "expired"
        await db.commit()
        raise HTTPException(status_code=401, detail="Token expired")
        
    ws = await db.get(Workspace, token.workspace_id)
    if not ws or not ws.is_active:
        raise HTTPException(status_code=403, detail="Workspace inactive or not found")
        
    token.last_used_at = datetime.utcnow()
    await db.commit()

    claims = {"sub": token.created_by, "workspace_id": token.workspace_id, "exp": datetime.utcnow() + timedelta(hours=1)}
    access_token = create_access_token(claims)
    
    return MachineExchangeResponse(
        access_token=access_token,
        token_type="bearer",
        workspace_id=token.workspace_id,
    )
