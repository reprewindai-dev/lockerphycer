"""Commercial entitlement routes.

Public (session):  GET  /api/v1/entitlements
                   GET  /api/v1/entitlements/usage
Admin:             POST /api/v1/entitlements/{workspace_id}/topup
                   POST /api/v1/entitlements/{workspace_id}/plan
Internal (CAPPO):  POST /api/v1/internal/entitlements/meter
                   POST /api/v1/internal/entitlements/reverse
                   POST /api/v1/internal/activation-events
"""

from __future__ import annotations

import hmac
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, Header, HTTPException, Query, status
from fastapi.responses import JSONResponse
from fastapi.security import HTTPAuthorizationCredentials
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.database.database import get_db
from core.entitlements import service as ent_service
from core.entitlements.activation import CAPPO_EVENTS, emit_activation_event
from core.entitlements.config import get_entitlement_settings
from core.security.auth import bearer, get_current_user, require_admin, verify_token
from db.models import User, Workspace

router = APIRouter()
internal_router = APIRouter()


def _error(exc: ent_service.EntitlementError) -> JSONResponse:
    return JSONResponse(status_code=exc.status_code, content={"error": exc.body})


async def _current_workspace(
    db: AsyncSession, user: User, credentials: HTTPAuthorizationCredentials | None
) -> Workspace:
    claimed = None
    if credentials is not None:
        claims = verify_token(credentials.credentials, expected_type="access")
        claimed = claims.get("workspace_id") or claims.get("tenant_id")
    if claimed:
        ws = await db.get(Workspace, claimed)
        if ws and ws.is_active and ws.owner_id == user.email:
            return ws
    ws = (
        await db.execute(
            select(Workspace)
            .where(Workspace.owner_id == user.email, Workspace.is_active == True)  # noqa: E712
            .order_by(Workspace.created_at.asc())
        )
    ).scalars().first()
    if ws is None:
        raise HTTPException(status_code=404, detail="No workspace bound to this operator")
    return ws


@router.get("")
@router.get("/")
async def get_entitlements(
    current_user: User = Depends(get_current_user),
    credentials: HTTPAuthorizationCredentials = Depends(bearer),
    db: AsyncSession = Depends(get_db),
):
    ws = await _current_workspace(db, current_user, credentials)
    now = ent_service._now()
    ent = await ent_service.ensure_entitlement(db, ws, now=now, lock=True)
    body = ent_service.snapshot(ent, now)
    body["subscription_status"] = ws.subscription_status
    await db.commit()
    return body


@router.get("/usage")
async def get_usage(
    since: Optional[datetime] = Query(None),
    until: Optional[datetime] = Query(None),
    current_user: User = Depends(get_current_user),
    credentials: HTTPAuthorizationCredentials = Depends(bearer),
    db: AsyncSession = Depends(get_db),
):
    """Per-workspace usage for the Day-14 "what Veklom is doing for you" view."""
    ws = await _current_workspace(db, current_user, credentials)
    now = ent_service._now()
    ent = await ent_service.ensure_entitlement(db, ws, now=now, lock=True)
    await db.commit()
    start = since.replace(tzinfo=None) if since else (ent.welcome_started_at or ent.period_start)
    end = until.replace(tzinfo=None) if until else now
    return await ent_service.usage_summary(db, ws.id, since=start, until=end)


class TopupRequest(BaseModel):
    credits: int = Field(gt=0)
    idempotency_key: str = Field(min_length=8, max_length=200)
    settlement_rail: str = Field(pattern=r"^(stripe_fiat|x402_base_usdc|manual)$")
    settlement_ref: Optional[str] = Field(default=None, max_length=255)


@router.post("/{workspace_id}/topup")
async def admin_topup(
    workspace_id: str,
    body: TopupRequest,
    admin_email: str = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Admin-only credit top-up (mirrors the admin-only wallet fund route).

    Stripe/x402 settlement wiring does not exist yet; this records credits only.
    """
    try:
        return await ent_service.grant_topup(
            db, workspace_id, body.credits,
            idempotency_key=f"topup:{body.idempotency_key}",
            settlement_rail=body.settlement_rail,
            settlement_ref=body.settlement_ref,
        )
    except ent_service.EntitlementError as exc:
        return _error(exc)


class PlanRequest(BaseModel):
    plan: str = Field(pattern=r"^(developer|pro|team|enterprise)$")
    monthly_credits: Optional[int] = Field(default=None, gt=0)


@router.post("/{workspace_id}/plan")
async def admin_set_plan(
    workspace_id: str,
    body: PlanRequest,
    admin_email: str = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    try:
        ent = await ent_service.set_plan(db, workspace_id, body.plan, monthly_credits=body.monthly_credits)
    except ent_service.EntitlementError as exc:
        return _error(exc)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return ent_service.snapshot(ent)


# ---------------------------------------------------------------------------
# Internal service-to-service endpoints (CAPPO)
# ---------------------------------------------------------------------------


def require_service_token(x_veklom_service_token: str | None = Header(default=None)) -> None:
    expected = get_entitlement_settings().ENTITLEMENTS_INTERNAL_TOKEN
    if not expected:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="internal metering not configured")
    if not x_veklom_service_token or not hmac.compare_digest(x_veklom_service_token, expected):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="invalid service token")


class MeterRequest(BaseModel):
    workspace_id: str = Field(min_length=1, max_length=36)
    action_type: str = Field(min_length=1, max_length=60)
    idempotency_key: str = Field(min_length=8, max_length=255)
    mount_id: Optional[str] = Field(default=None, max_length=160)
    execution_ref: Optional[str] = Field(default=None, max_length=160)
    operation_ref: Optional[str] = Field(default=None, max_length=160)
    principal: Optional[str] = Field(default=None, max_length=255)


@internal_router.post("/entitlements/meter", dependencies=[Depends(require_service_token)])
async def internal_meter(body: MeterRequest, db: AsyncSession = Depends(get_db)):
    try:
        result = await ent_service.debit(
            db, body.workspace_id, body.action_type,
            idempotency_key=body.idempotency_key,
            mount_id=body.mount_id, execution_ref=body.execution_ref,
            operation_ref=body.operation_ref, principal=body.principal,
        )
    except KeyError as exc:
        raise HTTPException(status_code=400, detail="unknown action_type") from exc
    except ent_service.EntitlementError as exc:
        return _error(exc)
    return result.as_dict()


class ReverseRequest(BaseModel):
    idempotency_key: str = Field(min_length=8, max_length=255)
    reason: str = Field(default="authority_denied", max_length=120)


@internal_router.post("/entitlements/reverse", dependencies=[Depends(require_service_token)])
async def internal_reverse(body: ReverseRequest, db: AsyncSession = Depends(get_db)):
    return await ent_service.reverse(db, body.idempotency_key, reason=body.reason)


class ActivationRequest(BaseModel):
    event_name: str = Field(min_length=1, max_length=60)
    workspace_id: str = Field(min_length=1, max_length=36)
    ref: Optional[str] = Field(default=None, max_length=255)
    details: dict = Field(default_factory=dict)


@internal_router.post("/activation-events", dependencies=[Depends(require_service_token)])
async def internal_activation_event(body: ActivationRequest, db: AsyncSession = Depends(get_db)):
    if body.event_name not in CAPPO_EVENTS:
        raise HTTPException(status_code=400, detail="event not accepted from CAPPO")
    recorded = await emit_activation_event(
        db, body.event_name, workspace_id=body.workspace_id, source="cappo",
        ref=body.ref, details=body.details,
    )
    return {"recorded": recorded}
