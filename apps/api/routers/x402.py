"""
x402 Payment-Gated API Router — Veklom Sovereign AI Hub

Implements the x402 protocol (HTTP 402 Payment Required) with:
- USDC on Base mainnet via Coinbase x402 facilitator
- Compliant `payment-required` header (base64-encoded JSON)
- /gate, /payment, /budget, /transactions endpoints
- Discovery document data provider (mounted in main.py at /.well-known/x402)
- Pricing aligned with /api/v1/billing/pricing ($0.10 USDC per gated call)

Protocol reference: https://docs.cdp.coinbase.com/x402
Facilitator:        https://x402.org/facilitator
"""

import base64
import json
import logging
import os
import uuid
from datetime import datetime, timezone
from typing import Optional

import httpx
from fastapi import APIRouter, Depends, Header, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel

logger = logging.getLogger(__name__)

router = APIRouter()

# ── Configuration ─────────────────────────────────────────────────────────────
# These MUST be set in your environment / Coolify secrets.
# Defaults are safe fallbacks for local dev only.

# Veklom production payment wallet (USDC settlements arrive here)
PAYMENT_WALLET: str = os.environ.get(
    "X402_PAYMENT_WALLET", "0xCC34553b4e6332ffb9C1b61E22436ACA53113D1d"
)

# USDC contract on Base Mainnet
USDC_BASE: str = os.environ.get(
    "X402_USDC_CONTRACT", "0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913"
)

# Coinbase x402 facilitator URL
FACILITATOR_URL: str = os.environ.get(
    "X402_FACILITATOR_URL", "https://x402.org/facilitator"
)

# Public API base URL (used to build resource URLs)
API_BASE_URL: str = os.environ.get(
    "X402_API_BASE_URL", "https://api.veklom.com"
)

# Price per gated API call in USDC — MUST match /api/v1/billing/pricing output
# Chet flagged a mismatch of $0.10 vs $0.80 — canonical value is $0.10 USDC.
PAYMENT_AMOUNT_USDC: float = float(
    os.environ.get("X402_PAYMENT_AMOUNT_USDC", "0.10")
)

# Max timeout (seconds) the facilitator waits for on-chain confirmation
MAX_TIMEOUT_SECONDS: int = int(os.environ.get("X402_MAX_TIMEOUT_SECONDS", "300"))

X402_VERSION: int = 1


# ── Helpers ───────────────────────────────────────────────────────────────────

def _usdc_units(usd_amount: float) -> str:
    """Convert a USD/USDC amount to micro-USDC units (6 decimals)."""
    return str(int(round(usd_amount * 1_000_000)))


def _build_payment_required(resource_path: str, description: str = "Veklom API access") -> dict:
    """
    Build an x402-compliant payment-required payload.

    Per the spec the `accepts` array lists acceptable payment schemes.
    `exact` scheme means the client must pay exactly `maxAmountRequired`.
    """
    resource_url = f"{API_BASE_URL}{resource_path}"
    return {
        "x402Version": X402_VERSION,
        "accepts": [
            {
                "scheme": "exact",
                "network": "base-mainnet",
                "maxAmountRequired": _usdc_units(PAYMENT_AMOUNT_USDC),
                "resource": resource_url,
                "description": description,
                "mimeType": "application/json",
                "payTo": PAYMENT_WALLET,
                "maxTimeoutSeconds": MAX_TIMEOUT_SECONDS,
                "asset": USDC_BASE,
                "extra": {
                    "name": "Veklom Sovereign AI Hub",
                    "version": str(X402_VERSION),
                },
            }
        ],
        "error": "Payment required",
    }


def _payment_required_response(resource_path: str, description: str = "Veklom API access") -> JSONResponse:
    """
    Return an HTTP 402 response with:
    - JSON body containing the x402 payment-required payload
    - `payment-required` header containing a base64-encoded version of the same payload

    The base64 header is the canonical x402 indicator that clients and
    middleware look for to detect a payment-gated endpoint.
    """
    payload = _build_payment_required(resource_path, description)
    payload_b64 = base64.b64encode(json.dumps(payload).encode()).decode()
    return JSONResponse(
        status_code=402,
        content=payload,
        headers={
            "payment-required": payload_b64,
            "x-x402-version": str(X402_VERSION),
        },
    )


async def _verify_payment(x_payment: str, resource_path: str) -> dict:
    """
    Call the Coinbase facilitator /verify endpoint.
    Returns the verification response dict on success.
    Raises HTTPException(402) on failure.
    """
    resource_url = f"{API_BASE_URL}{resource_path}"
    async with httpx.AsyncClient(timeout=30.0) as client:
        try:
            resp = await client.post(
                f"{FACILITATOR_URL}/verify",
                json={
                    "x402Version": X402_VERSION,
                    "paymentHeader": x_payment,
                    "resource": resource_url,
                },
            )
        except httpx.RequestError as exc:
            logger.error("x402 facilitator /verify unreachable: %s", exc)
            raise HTTPException(
                status_code=502, detail="Payment facilitator unreachable"
            )

    if resp.status_code != 200:
        body = resp.json() if resp.headers.get("content-type", "").startswith("application/json") else {}
        logger.warning("x402 /verify rejected — status=%s body=%s", resp.status_code, body)
        raise HTTPException(status_code=402, detail="Payment verification failed")

    return resp.json()


async def _settle_payment(x_payment: str, resource_path: str) -> None:
    """
    Call the Coinbase facilitator /settle endpoint.
    This triggers on-chain settlement of the verified payment.
    Errors are logged but do not fail the response (payment was verified).
    """
    resource_url = f"{API_BASE_URL}{resource_path}"
    async with httpx.AsyncClient(timeout=30.0) as client:
        try:
            await client.post(
                f"{FACILITATOR_URL}/settle",
                json={"paymentHeader": x_payment, "resource": resource_url},
            )
        except Exception as exc:
            logger.error("x402 /settle failed (payment was verified): %s", exc)


# ── x402 Dependency ───────────────────────────────────────────────────────────

async def require_x402_payment(
    request: Request,
    x_payment: Optional[str] = Header(None, alias="x-payment"),
) -> dict:
    """
    FastAPI dependency for x402 payment gating.

    Usage:
        @router.get("/my-endpoint")
        async def my_endpoint(payment: dict = Depends(require_x402_payment)):
            ...

    On first call (no x-payment header): returns HTTP 402 with challenge.
    On subsequent call (with x-payment header): verifies + settles via facilitator.
    Returns the verification result dict on success.
    """
    resource_path = request.url.path
    if not x_payment:
        raise _payment_required_response(resource_path) from None  # type: ignore[misc]
    return await _verify_payment(x_payment, resource_path)


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.get("/gate")
async def x402_gate(
    request: Request,
    x_payment: Optional[str] = Header(None, alias="x-payment"),
):
    """
    Primary x402 payment gate.

    - No x-payment header → HTTP 402 with payment-required challenge
    - Valid x-payment header → verifies on-chain, settles, returns 200
    """
    resource_path = "/api/v1/x402/gate"

    if not x_payment:
        return _payment_required_response(resource_path, "Veklom API gateway access — $0.10 USDC")

    verification = await _verify_payment(x_payment, resource_path)
    await _settle_payment(x_payment, resource_path)

    return JSONResponse(
        status_code=200,
        content={
            "access": "granted",
            "sessionId": str(uuid.uuid4()),
            "expiresIn": 1800,
            "paidAt": datetime.now(timezone.utc).isoformat(),
            "verification": verification,
        },
        headers={"x-payment-response": base64.b64encode(json.dumps({"success": True}).encode()).decode()},
    )


@router.get("/payment")
async def x402_payment_info(request: Request):
    """
    Returns the current payment terms without requiring payment.
    Useful for clients to pre-inspect the payment requirements.
    """
    resource_path = "/api/v1/x402/gate"
    return _build_payment_required(resource_path, "Veklom API gateway access — $0.10 USDC")


class BudgetRequest(BaseModel):
    wallet_address: str
    max_spend_usdc: float
    duration_seconds: int = 86400


@router.post("/budget")
async def x402_budget(
    request: Request,
    body: BudgetRequest,
    x_payment: Optional[str] = Header(None, alias="x-payment"),
):
    """
    Budget endpoint: allows a client to declare a spending ceiling.
    Gated behind a $0.10 USDC setup fee.

    AI agents (e.g. Claude, OpenAI Agents SDK) use budget endpoints to
    pre-authorise a session spend envelope before making multiple calls.
    """
    resource_path = "/api/v1/x402/budget"

    if not x_payment:
        return _payment_required_response(resource_path, "Budget session setup — $0.10 USDC")

    verification = await _verify_payment(x_payment, resource_path)
    await _settle_payment(x_payment, resource_path)

    budget_id = str(uuid.uuid4())
    return JSONResponse(
        status_code=200,
        content={
            "budgetId": budget_id,
            "walletAddress": body.wallet_address,
            "maxSpendUsdc": body.max_spend_usdc,
            "pricePerCallUsdc": PAYMENT_AMOUNT_USDC,
            "estimatedCalls": int(body.max_spend_usdc / PAYMENT_AMOUNT_USDC),
            "durationSeconds": body.duration_seconds,
            "createdAt": datetime.now(timezone.utc).isoformat(),
            "verification": verification,
        },
        headers={"x-payment-response": base64.b64encode(json.dumps({"success": True}).encode()).decode()},
    )


@router.get("/transactions")
async def x402_transactions(
    request: Request,
    x_payment: Optional[str] = Header(None, alias="x-payment"),
    limit: int = 20,
    offset: int = 0,
):
    """
    Returns recent x402 transaction history for authenticated callers.
    Gated — requires a valid x-payment header.

    In a production deployment this would query the database for
    WalletTransaction rows filtered to x402 event_type.
    Currently returns a structured stub response while DB wiring is pending.
    """
    resource_path = "/api/v1/x402/transactions"

    if not x_payment:
        return _payment_required_response(resource_path, "Transaction history access — $0.10 USDC")

    verification = await _verify_payment(x_payment, resource_path)
    await _settle_payment(x_payment, resource_path)

    return JSONResponse(
        status_code=200,
        content={
            "transactions": [],
            "total": 0,
            "limit": limit,
            "offset": offset,
            "note": "DB-backed transaction history is queued for the next sprint.",
            "verification": verification,
        },
        headers={"x-payment-response": base64.b64encode(json.dumps({"success": True}).encode()).decode()},
    )


# ── Discovery Document Helper ──────────────────────────────────────────────────
# This is returned by the /.well-known/x402 endpoint registered in main.py.
# It MUST only describe x402 payment methods — no Stripe, PayPal, or wire.

def get_discovery_document() -> dict:
    """
    Returns a spec-compliant x402 discovery document.
    Mounted at /.well-known/x402 in main.py.

    Only x402 / USDC / Base entries are listed.
    Generic billing providers (Stripe, PayPal, wire) must NOT appear here.
    """
    return {
        "x402Version": X402_VERSION,
        "provider": "Veklom Sovereign AI Hub",
        "network": "base-mainnet",
        "asset": USDC_BASE,
        "payTo": PAYMENT_WALLET,
        "facilitator": FACILITATOR_URL,
        "schemes": ["exact"],
        "endpoints": [
            {
                "path": "/api/v1/x402/gate",
                "description": "Primary payment gate",
                "priceUsdc": PAYMENT_AMOUNT_USDC,
            },
            {
                "path": "/api/v1/x402/budget",
                "description": "Session budget pre-authorisation",
                "priceUsdc": PAYMENT_AMOUNT_USDC,
            },
            {
                "path": "/api/v1/x402/transactions",
                "description": "x402 transaction history",
                "priceUsdc": PAYMENT_AMOUNT_USDC,
            },
            {
                "path": "/api/v1/x402/payment",
                "description": "Payment terms inspector (free)",
                "priceUsdc": 0,
            },
        ],
        "pricingReference": "/api/v1/billing/pricing",
        "documentation": "https://docs.cdp.coinbase.com/x402",
    }
