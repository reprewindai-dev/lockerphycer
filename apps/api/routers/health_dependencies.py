"""Bounded dependency health probes for Lockerphycer."""

from __future__ import annotations

import asyncio
import time
from typing import Any
from urllib.parse import urlparse

import httpx
from fastapi import APIRouter
from sqlalchemy import text

from core.config.settings import settings
from core.database.database import engine

router = APIRouter(tags=["Health"])

_PROBE_TIMEOUT_SECONDS = 2.0
_STATE_RANK = {"healthy": 0, "degraded": 1, "unconfigured": 1, "unavailable": 2}


def _host(url: str) -> str:
    return urlparse(url).hostname or "unknown"


def _result(name: str, host: str, state: str, started: float) -> dict[str, Any]:
    return {
        "name": name,
        "host": host,
        "state": state,
        "latency_ms": round((time.perf_counter() - started) * 1000, 2),
    }


def _unconfigured(name: str) -> dict[str, Any]:
    return {"name": name, "host": "unconfigured", "state": "unconfigured", "latency_ms": 0.0}


async def _probe_database() -> dict[str, Any]:
    started = time.perf_counter()

    async def check() -> None:
        async with engine.connect() as connection:
            await connection.execute(text("SELECT 1"))

    try:
        await asyncio.wait_for(check(), timeout=_PROBE_TIMEOUT_SECONDS)
        state = "healthy"
    except Exception:  # noqa: BLE001 - probes must never raise
        state = "unavailable"
    return _result("database", "configured", state, started)


async def _probe_redis(redis_url: str) -> dict[str, Any]:
    started = time.perf_counter()
    parsed = urlparse(redis_url)
    host = parsed.hostname or "unknown"
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
            await asyncio.wait_for(reader.readline(), timeout=_PROBE_TIMEOUT_SECONDS)
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
    return _result("redis", host, state, started)


async def _probe_http(name: str, base_url: str) -> dict[str, Any]:
    started = time.perf_counter()
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
        state = "healthy" if 200 <= response.status_code < 300 else "degraded"
    except Exception:  # noqa: BLE001 - probes must never raise
        state = "unavailable"
    return _result(name, _host(base_url), state, started)


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
    return {"status": overall, "dependencies": checks}
