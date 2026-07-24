"""
apps/api/routers/mfa.py

Thin routing layer over the tested core/security/mfa.py service. Follows
the same get_current_user dependency pattern already used elsewhere in
this repo's routers — no new auth pattern introduced.
"""
from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from core.database.database import get_db
from core.security.auth import get_current_user
from core.security.mfa import setup_mfa, confirm_mfa_setup, verify_mfa_code, disable_mfa
from db.models import User

router = APIRouter(prefix="/auth/mfa", tags=["mfa"])


class ConfirmMFARequest(BaseModel):
    secret: str
    code: str


class VerifyMFARequest(BaseModel):
    code: str


class DisableMFARequest(BaseModel):
    code: str


@router.post("/setup")
async def start_mfa_setup(current_user: User = Depends(get_current_user)):
    if current_user.mfa_enabled:
        raise HTTPException(status_code=400, detail="MFA is already enabled")
    result = setup_mfa(current_user.email)
    # secret only ever returned here, at setup time — never re-displayed after confirm
    return {"secret": result["secret"], "provisioning_uri": result["provisioning_uri"]}


@router.get("/setup/qr")
async def get_setup_qr(current_user: User = Depends(get_current_user)):
    result = setup_mfa(current_user.email)
    return Response(content=result["qr_code_png_bytes"], media_type="image/png")


@router.post("/confirm")
async def confirm_setup(
    body: ConfirmMFARequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    backup_codes = await confirm_mfa_setup(db, current_user, body.secret, body.code)
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
