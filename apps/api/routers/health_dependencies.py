"""Bounded dependency health probes for Lockerphycer.

This endpoint intentionally distinguishes local dependency health from external
Veklom service reachability. A 2xx response from another service is not proof of
that service's protocol identity, deployment SHA, listener, or routing chain.
"""

from __future__ import annotations

import asyncio
from typing import Any

import httpx
from fastapi import APIRouter
from sqlalchemy import text

from core.config.settings import settings
from core.database.database import engine

router = APIRouter(tags=["Health"])

_PROBE_TIMEOUT_SECONDS = 2.0
_STATE_RANK = {
    "healthy": 0,
    "reachable_not_verified": 1,
    "degraded": 2,
    "unconfigured": 2,
    "unavailable": 3,
}


def _result(name: str, state: str, verification_scope: str) -> dict[str, Any]:
    """Return only non-sensitive public health metadata."""
    return {
        "name": name,
        "state": state,
        "verification_scope": verification_scope,
    }


def _unconfigured(name: str) -> dict[str, Any]:
    return _result(name, "unconfigured", "NOT_VERIFIED")


def _external_http_state(status_code: int) -> str:
    """HTTP success proves reachability only, never foundation identity."""
    return "reachable_not_verified" if 200 <= status_code < 300 else "degraded"


async def _probe_database() -> dict[str, Any]:
    async def check() -> None:
        async with engine.connect() as connection:
            await connection.execute(text("SELECT 1"))

    try:
        await asyncio.wait_for(check(), timeout=_PROBE_TIMEOUT_SECONDS)
        state = "healthy"
    except Exception:  # noqa: BLE001 - probes must never raise
        state = "unavailable"
    return _result("database", state, "LOCAL_QUERY")


async def _probe_redis(redis_url: str) -> dict[str, Any]:
    from urllib.parse import urlparse

    parsed = urlparse(redis_url)
    host = parsed.hostname or ""
    port = parsed.port or 6379
    writer = None
    try:
        reader, writer = await asyncio.wait_for(
            asyncio.open_connection(host, port),
            timeout=_PROBE_TIMEOUT_SECONDS,
        )
        if parsed.password:
            writer.write(
                f"*2\r\n$4\r\nAUTH\r\n${len(parsed.password.encode())}\r\n{parsed.password}\r\n".encode()
            )
            await writer.drain()
            auth_response = await asyncio.wait_for(reader.readline(), timeout=_PROBE_TIMEOUT_SECONDS)
            if not auth_response.startswith(b"+OK"):
                return _result("redis", "degraded", "LOCAL_PROTOCOL")
        writer.write(b"*1\r\n$4\r\nPING\r\n")
        await writer.drain()
        response = await asyncio.wait_for(reader.readline(), timeout=_PROBE_TIMEOUT_SECONDS)
        state = "healthy" if response.startswith((b"+PONG", b":1")) else "degraded"
    except Exception:  # noqa: BLE001 - probes must never raise
        state = "unavailable"
    finally:
        if writer is not None:
            writer.close()
            await writer.wait_closed()
    return _result("redis", state, "LOCAL_PROTOCOL")


async def _probe_http(name: str, base_url: str) -> dict[str, Any]:
    base = base_url.rstrip("/")
    try:
        timeout = httpx.Timeout(_PROBE_TIMEOUT_SECONDS)
        async with httpx.AsyncClient(timeout=timeout, follow_redirects=False) as client:
            response = await asyncio.wait_for(
                client.get(f"{base}/health"),
                timeout=_PROBE_TIMEOUT_SECONDS,
            )
            if response.status_code == 404:
                response = await asyncio.wait_for(
                    client.get(f"{base}/protocol.json"),
                    timeout=_PROBE_TIMEOUT_SECONDS,
                )
        state = _external_http_state(response.status_code)
    except Exception:  # noqa: BLE001 - probes must never raise
        state = "unavailable"
    return _result(name, state, "HTTP_REACHABILITY_ONLY")


@router.get("/health/dependencies", include_in_schema=False)
async def dependency_health() -> dict[str, Any]:
    checks = [await _probe_database()]

    redis_url = getattr(settings, "REDIS_URL", "")
    checks.append(await _probe_redis(redis_url) if redis_url else _unconfigured("redis"))

    for name, url in (
        ("capi", getattr(settings, "CAPI_BACKEND_URL", None)),
        ("cappo", getattr(settings, "CAPPO_BACKEND_URL", None)),
        ("pgl", getattr(settings, "PGL_LEDGER_URL", None)),
        ("byos", getattr(settings, "BYOS_MCP_GATEWAY_URL", None)),
    ):
        checks.append(await _probe_http(name, url) if url else _unconfigured(name))

    overall = max(checks, key=lambda check: _STATE_RANK[check["state"]])["state"]
    return {
        "status": overall,
        "verification_scope": "DEPENDENCY_HEALTH_NOT_RUNTIME_VERIFICATION",
        "dependencies": checks,
    }
