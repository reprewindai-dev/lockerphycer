"""Veklom Wallet routes (Base): bind a SIWE-proven wallet to the workspace.

Session (operator bearer):
  GET  /api/v1/wallet                  current workspace wallet (or null)
  GET  /api/v1/wallet/config           network, treasury and credit tokens
  POST /api/v1/wallet/nonce            single-use SIWE nonce for this workspace
  POST /api/v1/wallet/register         verify EIP-4361 message + signature, bind
  POST /api/v1/wallet/topups/onchain   verify a Base transfer receipt, credit
  GET  /api/v1/wallet/onboarding       Capability OS checklist state

A wallet is never required to explore or during Welcome; it is required only
before funding-dependent or externally settled actions. Stripe (how a company
pays Veklom) is separate: /api/v1/billing/checkout.
"""

from __future__ import annotations

import logging
import secrets
from datetime import datetime, timedelta, timezone
from typing import Optional

from eth_utils import to_checksum_address
from fastapi import APIRouter, Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials
from pydantic import BaseModel, Field
from sqlalchemy import or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.routers.entitlements import _current_workspace
from core.config.settings import settings as app_settings
from core.database.database import get_db
from core.entitlements import service as ent_service
from core.entitlements.activation import emit_activation_event
from core.entitlements.config import get_entitlement_settings
from core.security.auth import bearer, get_current_user
from core.wallet import rpc as wallet_rpc
from core.wallet.config import get_wallet_settings
from core.wallet.rpc import RpcUnavailable
from core.wallet.signature import SignatureInvalid, verify_personal_signature
from core.wallet.siwe import SiweError, check_fields, parse_message
from core.wallet.topup import TopupPending, TopupRejected, normalize_tx_hash, verify_topup
from db.models import ActivationEvent, User, WalletNonce, WorkspaceWallet

logger = logging.getLogger(__name__)
router = APIRouter()

WALLET_PROVIDERS = {"cdp_embedded", "base_account", "walletconnect", "injected", "coinbase_wallet", "other"}


def _utcnow() -> datetime:
    return datetime.utcnow()


def _wallet_view(w: WorkspaceWallet | None) -> dict | None:
    if w is None:
        return None
    return {
        "address": w.address,
        "chain_id": w.chain_id,
        "source": w.source,
        "wallet_provider": w.wallet_provider,
        "signature_kind": w.signature_kind,
        "verified_at": w.verified_at.isoformat() + "Z",
    }


async def _active_wallet(db: AsyncSession, workspace_id: str, chain_id: int) -> WorkspaceWallet | None:
    return (
        await db.execute(
            select(WorkspaceWallet)
            .where(WorkspaceWallet.workspace_id == workspace_id, WorkspaceWallet.chain_id == chain_id,
                   WorkspaceWallet.revoked_at.is_(None))
            .order_by(WorkspaceWallet.verified_at.desc())
        )
    ).scalars().first()


def _network_view() -> dict:
    cfg = get_wallet_settings()
    net = cfg.network
    return {"network": net.key, "chain_id": net.chain_id, "name": net.name, "explorer": net.explorer,
            "testnet": net.key != "base"}


@router.get("")
@router.get("/")
async def get_wallet(
    current_user: User = Depends(get_current_user),
    credentials: HTTPAuthorizationCredentials = Depends(bearer),
    db: AsyncSession = Depends(get_db),
):
    ws = await _current_workspace(db, current_user, credentials)
    net = get_wallet_settings().network
    wallet = await _active_wallet(db, ws.id, net.chain_id)
    return {"workspace_id": ws.id, **_network_view(), "wallet": _wallet_view(wallet)}


@router.get("/config")
async def get_wallet_config(current_user: User = Depends(get_current_user)):
    cfg = get_wallet_settings()
    treasury = cfg.WALLET_TREASURY_ADDRESS.strip()
    return {
        **_network_view(),
        "treasury_address": to_checksum_address(treasury) if treasury else None,
        "onchain_topup_enabled": bool(treasury),
        "credit_tokens": [
            {"symbol": t.symbol, "address": to_checksum_address(t.address), "decimals": t.decimals,
             "usd_per_token": t.usd_per_token}
            for t in cfg.credit_tokens()
        ],
        "credits_per_usd": get_entitlement_settings().TOPUP_CREDITS_PER_USD,
        "min_confirmations": cfg.WALLET_MIN_CONFIRMATIONS,
        "stripe_topups": ["topup_50", "topup_100", "topup_500"],
    }


@router.post("/nonce")
async def issue_nonce(
    current_user: User = Depends(get_current_user),
    credentials: HTTPAuthorizationCredentials = Depends(bearer),
    db: AsyncSession = Depends(get_db),
):
    ws = await _current_workspace(db, current_user, credentials)
    cfg = get_wallet_settings()
    nonce = secrets.token_hex(16)  # 32 alphanumeric chars (EIP-4361: >= 8)
    now = _utcnow()
    expires = now + timedelta(seconds=cfg.WALLET_NONCE_TTL_SECONDS)
    db.add(WalletNonce(nonce=nonce, workspace_id=ws.id, issued_to=current_user.email, expires_at=expires, created_at=now))
    await db.commit()
    return {"nonce": nonce, "expires_at": expires.isoformat() + "Z", "chain_id": cfg.network.chain_id,
            "domains": sorted(cfg.siwe_domains(app_settings.FRONTEND_URL))}


class RegisterRequest(BaseModel):
    message: str = Field(min_length=40, max_length=4096)
    signature: str = Field(min_length=4, max_length=40_000)
    source: str = Field(pattern=r"^(created|connected)$")
    wallet_provider: Optional[str] = Field(default=None, max_length=60)


@router.post("/register")
async def register_wallet(
    body: RegisterRequest,
    current_user: User = Depends(get_current_user),
    credentials: HTTPAuthorizationCredentials = Depends(bearer),
    db: AsyncSession = Depends(get_db),
):
    ws = await _current_workspace(db, current_user, credentials)
    ws_id = ws.id
    cfg = get_wallet_settings()
    chain_id = cfg.network.chain_id
    try:
        msg = parse_message(body.message)
        check_fields(msg, allowed_domains=cfg.siwe_domains(app_settings.FRONTEND_URL), chain_id=chain_id,
                     now=datetime.now(timezone.utc), max_age_seconds=cfg.WALLET_SIWE_MAX_AGE_SECONDS)
    except SiweError as exc:
        raise HTTPException(status_code=400, detail=f"invalid sign-in message: {exc}") from exc

    now = _utcnow()
    nonce_row = await db.get(WalletNonce, msg.nonce)
    if (nonce_row is None or nonce_row.workspace_id != ws_id or nonce_row.used_at is not None
            or nonce_row.expires_at <= now):
        raise HTTPException(status_code=400, detail="invalid, expired or reused nonce")

    try:
        result = await verify_personal_signature(wallet_rpc.rpc_factory(), msg.address, body.message, body.signature)
    except SignatureInvalid as exc:
        raise HTTPException(status_code=400, detail=f"wallet signature not valid: {exc}") from exc
    except RpcUnavailable as exc:
        raise HTTPException(status_code=502, detail="Base RPC unavailable; try again") from exc

    # Consume the nonce atomically: only one request can flip used_at.
    consumed = await db.execute(
        update(WalletNonce).where(WalletNonce.nonce == msg.nonce, WalletNonce.used_at.is_(None)).values(used_at=now)
    )
    if consumed.rowcount != 1:
        await db.rollback()
        raise HTTPException(status_code=400, detail="invalid, expired or reused nonce")

    address = to_checksum_address(msg.address)
    provider = body.wallet_provider if body.wallet_provider in WALLET_PROVIDERS else ("other" if body.wallet_provider else None)
    current = await _active_wallet(db, ws_id, chain_id)
    if current is not None and current.address != address:
        current.revoked_at = now
    existing = (
        await db.execute(select(WorkspaceWallet).where(
            WorkspaceWallet.workspace_id == ws_id, WorkspaceWallet.chain_id == chain_id,
            WorkspaceWallet.address == address))
    ).scalars().first()
    if existing is None:
        existing = WorkspaceWallet(workspace_id=ws_id, chain_id=chain_id, address=address, created_at=now)
        db.add(existing)
    existing.source = body.source
    existing.wallet_provider = provider
    existing.signature_kind = result.kind
    existing.siwe_message = body.message
    existing.siwe_signature = body.signature
    existing.siwe_nonce = msg.nonce
    existing.verified_by = current_user.email
    existing.verified_at = now
    existing.revoked_at = None
    await db.commit()
    await db.refresh(existing)
    view = _wallet_view(existing)

    event = "wallet_created" if body.source == "created" else "wallet_connected"
    await emit_activation_event(db, event, workspace_id=ws_id, ref=f"eip155:{chain_id}:{address}",
                                details={"provider": provider, "signature_kind": result.kind})
    return {"workspace_id": ws_id, **_network_view(), "wallet": view}


class OnchainTopupRequest(BaseModel):
    tx_hash: str = Field(min_length=66, max_length=66)


@router.post("/topups/onchain")
async def onchain_topup(
    body: OnchainTopupRequest,
    current_user: User = Depends(get_current_user),
    credentials: HTTPAuthorizationCredentials = Depends(bearer),
    db: AsyncSession = Depends(get_db),
):
    ws = await _current_workspace(db, current_user, credentials)
    ws_id = ws.id
    cfg = get_wallet_settings()
    treasury = cfg.WALLET_TREASURY_ADDRESS.strip()
    if not treasury:
        raise HTTPException(status_code=503, detail="onchain top-ups are not configured")
    try:
        tx_hash = normalize_tx_hash(body.tx_hash)
    except TopupRejected as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    chain_id = cfg.network.chain_id
    payers = {
        w.address for w in (await db.execute(select(WorkspaceWallet).where(
            WorkspaceWallet.workspace_id == ws_id, WorkspaceWallet.chain_id == chain_id))).scalars()
    }
    if not payers:
        raise HTTPException(status_code=409, detail="bind a wallet to this workspace before an onchain top-up")
    try:
        verified = await verify_topup(
            wallet_rpc.rpc_factory(), tx_hash=tx_hash, chain_id=chain_id, treasury=treasury, payers=payers,
            tokens=cfg.credit_tokens(), min_confirmations=cfg.WALLET_MIN_CONFIRMATIONS,
            credits_per_usd=get_entitlement_settings().TOPUP_CREDITS_PER_USD)
    except TopupPending as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except TopupRejected as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except RpcUnavailable as exc:
        raise HTTPException(status_code=502, detail="Base RPC unavailable; try again") from exc

    try:
        grant = await ent_service.grant_topup(
            db, ws_id, verified.credits, idempotency_key=f"onchain:{chain_id}:{tx_hash}",
            settlement_rail="base_onchain_transfer", settlement_ref=f"eip155:{chain_id}:{tx_hash}")
    except ent_service.EntitlementError as exc:  # includes IdempotencyConflict (claimed elsewhere)
        raise HTTPException(status_code=409, detail="this transaction was already credited") from exc
    if not grant.get("replay"):
        await emit_activation_event(db, "funding_method_added", workspace_id=ws_id, ref="base_onchain",
                                    details={"tokens": sorted({t["token"] for t in verified.transfers}),
                                             "chain_id": chain_id})
    return {"credited": not grant.get("replay"), "replay": bool(grant.get("replay")), "credits": verified.credits,
            "usd": str(verified.usd), "tx_hash": tx_hash, "chain_id": chain_id, "balance": grant.get("balance")}


CHECKLIST_EVENTS = {
    "capability": "capability_issued",
    "runtime": "system_connected",
    "first_execution": "first_governed_execution",
}


@router.get("/onboarding")
async def onboarding_state(
    current_user: User = Depends(get_current_user),
    credentials: HTTPAuthorizationCredentials = Depends(bearer),
    db: AsyncSession = Depends(get_db),
):
    """Checklist: Identity / Wallet / Capability / Connect runtime / First governed execution."""
    ws = await _current_workspace(db, current_user, credentials)
    net = get_wallet_settings().network
    wallet = await _active_wallet(db, ws.id, net.chain_id)
    # Signup and email verification happen before a workspace exists, so they are
    # recorded against the user only; count those alongside the workspace's events.
    names = set((await db.execute(
        select(ActivationEvent.event_name).where(
            or_(ActivationEvent.workspace_id == ws.id, ActivationEvent.user_id == current_user.id)
        ))).scalars())
    return {
        "workspace_id": ws.id,
        "identity": True,
        "email_verified": "email_verified" in names,
        "wallet": wallet is not None,
        "wallet_address": wallet.address if wallet else None,
        "funded": "funding_method_added" in names,
        **{key: event in names for key, event in CHECKLIST_EVENTS.items()},
    }
