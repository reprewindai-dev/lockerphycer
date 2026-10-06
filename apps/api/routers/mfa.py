"""
apps/api/routers/mfa.py

Thin routing layer over the tested core/security/mfa.py service. Follows
the same get_current_user dependency pattern already used elsewhere in
this repo's routers — no new auth pattern introduced.

The TOTP secret never round-trips through the client: /setup stores it as
the account's pending secret, /setup/qr renders that same secret, and
/confirm only takes the code the authenticator produced.
"""
from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from core.database.database import get_db
from core.security.auth import get_current_user
from core.security.mfa import (
    begin_mfa_setup,
    confirm_mfa_setup,
    disable_mfa,
    pending_mfa_secret,
    render_mfa_qr,
    verify_mfa_code,
)
from db.models import User

router = APIRouter(prefix="/auth/mfa", tags=["mfa"])


class ConfirmMFARequest(BaseModel):
    code: str


class VerifyMFARequest(BaseModel):
    code: str


class DisableMFARequest(BaseModel):
    code: str


@router.post("/setup")
async def start_mfa_setup(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    if current_user.mfa_enabled:
        raise HTTPException(status_code=400, detail="MFA is already enabled")
    result = await begin_mfa_setup(db, current_user)
    # secret only ever returned here, at setup time — never re-displayed after confirm
    return {"secret": result["secret"], "provisioning_uri": result["provisioning_uri"]}


@router.get("/setup/qr")
async def get_setup_qr(current_user: User = Depends(get_current_user)):
    secret = pending_mfa_secret(current_user)
    if not secret:
        raise HTTPException(status_code=404, detail="No MFA setup in progress")
    return Response(content=render_mfa_qr(current_user.email, secret), media_type="image/png")


@router.post("/confirm")
async def confirm_setup(
    body: ConfirmMFARequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    if not pending_mfa_secret(current_user):
        raise HTTPException(status_code=400, detail="No MFA setup in progress")
    backup_codes = await confirm_mfa_setup(db, current_user, body.code)
    if backup_codes is None:
        raise HTTPException(status_code=400, detail="Invalid code — MFA not enabled")
    # shown exactly once — client must display/store these immediately
    return {"mfa_enabled": True, "backup_codes": backup_codes}


@router.post("/verify")
async def verify(
    body: VerifyMFARequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    ok = await verify_mfa_code(db, current_user, body.code)
    if not ok:
        raise HTTPException(status_code=401, detail="Invalid MFA code")
    return {"verified": True}


@router.post("/disable")
async def disable(
    body: DisableMFARequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    ok = await disable_mfa(db, current_user, body.code)
    if not ok:
        raise HTTPException(status_code=401, detail="Invalid code — MFA not disabled")
    return {"mfa_enabled": False}
