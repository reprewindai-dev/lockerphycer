import asyncio
import logging
import os
from typing import Any

import httpx

from core.config.settings import Settings

logger = logging.getLogger(__name__)

REGISTRATION_TIMEOUT_SECONDS = 5.0
RETRY_SECONDS = 5.0
DEFAULT_REGISTRY_TTL_MS = 300_000


def build_registration_payload() -> dict[str, Any]:
    """Build endpoint-backed capabilities for cAPI discovery."""
    return {
        "service_name": "lockerphycer",
        "base_url": "https://command.veklom.com",
        "telemetry_supported": True,
        "capabilities": [
            {
                "name": "authenticate_users",
                "description": "Authenticate a Lockerphycer user and issue session tokens.",
                "endpoint": "https://command.veklom.com/api/v1/auth/login",
                "input_schema": {
                    "type": "object",
                    "required": ["email", "password"],
                    "properties": {
                        "email": {"type": "string", "format": "email"},
                        "password": {"type": "string", "format": "password"},
                    },
                },
                "risk_level": "high",
                "requires_approval": False,
            },
            {
                "name": "retrieve_current_identity",
                "description": "Retrieve the authenticated user's Lockerphycer identity.",
                "endpoint": "https://command.veklom.com/api/v1/auth/me",
                "input_schema": {"type": "object", "properties": {}},
                "risk_level": "low",
                "requires_approval": False,
            },
            {
                "name": "register_users",
                "description": "Create a Lockerphycer user identity.",
                "endpoint": "https://command.veklom.com/api/v1/auth/register",
                "input_schema": {
                    "type": "object",
                    "required": ["email", "username", "full_name", "password"],
                    "properties": {
                        "email": {"type": "string", "format": "email"},
                        "username": {"type": "string"},
                        "full_name": {"type": "string"},
                        "password": {"type": "string", "format": "password"},
                    },
                },
                "risk_level": "high",
                "requires_approval": True,
            },
            {
                "name": "inspect_agent_identity",
                "description": "Read an agent definition from the Lockerphycer registry.",
                "endpoint": "https://command.veklom.com/api/v1/agents/registry/{agent_number}",
                "input_schema": {
                    "type": "object",
                    "required": ["agent_number"],
                    "properties": {"agent_number": {"type": "integer"}},
                },
                "risk_level": "low",
                "requires_approval": False,
            },
        ],
        "metadata": {
            "protocol": "veklom-service-registration-v1",
            "manifest": "https://command.veklom.com/protocol.json",
        },
    }


def _heartbeat_interval_seconds(settings: Settings) -> float:
    raw_ttl = getattr(settings, "CAPI_REGISTRY_TTL_MS", os.getenv("CAPI_REGISTRY_TTL_MS", DEFAULT_REGISTRY_TTL_MS))
    try:
        ttl_ms = int(raw_ttl)
    except (TypeError, ValueError):
        ttl_ms = DEFAULT_REGISTRY_TTL_MS
    if ttl_ms <= 0:
        ttl_ms = DEFAULT_REGISTRY_TTL_MS
    return max(ttl_ms / 1_000 * 0.8, 0.001)


async def _wait_for_stop(stop: asyncio.Event, seconds: float) -> None:
    try:
        await asyncio.wait_for(stop.wait(), timeout=seconds)
    except TimeoutError:
        pass


def _registry_url(settings: Settings, path: str) -> str | None:
    base_url = (settings.CAPI_BACKEND_URL or "").strip()
    return f"{base_url.rstrip('/')}{path}" if base_url else None


def _headers(settings: Settings) -> dict[str, str]:
    headers = {"Content-Type": "application/json"}
    if settings.CAPI_API_KEY:
        headers["Authorization"] = f"Bearer {settings.CAPI_API_KEY}"
    return headers


async def register_with_capi(
    settings: Settings, transport: httpx.AsyncBaseTransport | None = None
) -> bool:
    """Register Lockerphycer once; callers decide when a failed attempt is retried."""
    url = _registry_url(settings, "/api/v1/registry/register")
    if not url:
        logger.info("cAPI registration skipped: CAPI_BACKEND_URL is not configured")
        return False

    try:
        async with httpx.AsyncClient(timeout=REGISTRATION_TIMEOUT_SECONDS, transport=transport) as client:
            response = await client.post(url, json=build_registration_payload(), headers=_headers(settings))
    except httpx.HTTPError as exc:
        logger.warning("cAPI registration failed (%s)", type(exc).__name__)
        return False

    if response.status_code in (200, 201):
        logger.info("Lockerphycer registered with cAPI")
        return True
    logger.warning("cAPI registration rejected with status %s", response.status_code)
    return False


async def heartbeat_until_missing(
    settings: Settings, stop: asyncio.Event, transport: httpx.AsyncBaseTransport | None = None
) -> bool:
    """Refresh Lockerphycer registration until cAPI reports it missing or shutdown begins."""
    url = _registry_url(settings, "/api/v1/registry/heartbeat")
    if not url:
        return False

    while not stop.is_set():
        await _wait_for_stop(stop, _heartbeat_interval_seconds(settings))
        if stop.is_set():
            return False
        try:
            async with httpx.AsyncClient(timeout=REGISTRATION_TIMEOUT_SECONDS, transport=transport) as client:
                response = await client.post(
                    url,
                    json={"service_name": "lockerphycer"},
                    headers=_headers(settings),
                )
        except httpx.HTTPError as exc:
            logger.warning("cAPI heartbeat failed (%s)", type(exc).__name__)
            continue

        if 200 <= response.status_code < 300:
            continue
        if response.status_code == 404:
            logger.info("Lockerphycer cAPI registration is missing; re-registering")
            return True
        logger.warning("cAPI heartbeat rejected with status %s", response.status_code)
    return False


async def maintain_capi_registration(
    settings: Settings, stop: asyncio.Event, transport: httpx.AsyncBaseTransport | None = None
) -> None:
    """Keep Lockerphycer registered without treating transport health as authority."""
    while not stop.is_set():
        if await register_with_capi(settings, transport):
            await heartbeat_until_missing(settings, stop, transport)
        else:
            await _wait_for_stop(stop, RETRY_SECONDS)
