"""
GPC Engine Proxy — reverse-proxies the uacpgemini Deterministic Engine
through the lockerphycer backend so every request is audited.
"""

from fastapi import APIRouter, Request, Response, Depends
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession
import httpx
import uuid
import logging
from datetime import datetime

from core.database.database import get_db
from db.models import AuditLog

router = APIRouter()
logger = logging.getLogger(__name__)

UPSTREAM = "https://uacpgemini.onrender.com"

# Reusable async client (connection pooling)
_client = httpx.AsyncClient(base_url=UPSTREAM, timeout=30.0, follow_redirects=True)

# Headers we should NOT forward downstream
HOP_HEADERS = frozenset(
    h.lower()
    for h in [
        "host",
        "connection",
        "keep-alive",
        "transfer-encoding",
        "te",
        "trailer",
        "upgrade",
        "proxy-authorization",
        "proxy-authenticate",
    ]
)


async def _audit(db: AsyncSession, method: str, path: str, status: int):
    """Log proxied request to the audit table for compliance."""
    try:
        log = AuditLog(
            id=str(uuid.uuid4()),
            action=f"GPC_PROXY_{method}",
            resource_type="gpc_engine",
            resource_id=path,
            new_values={
                "upstream": UPSTREAM,
                "path": path,
                "method": method,
                "status_code": status,
                "timestamp": datetime.utcnow().isoformat(),
            },
        )
        db.add(log)
        await db.commit()
    except Exception as exc:
        logger.warning("Audit log write failed: %s", exc)


@router.api_route("/{path:path}", methods=["GET", "POST", "PUT", "DELETE", "PATCH", "OPTIONS"])
async def proxy(path: str, request: Request, db: AsyncSession = Depends(get_db)):
    """Forward every request to the upstream uacpgemini server."""
    upstream_url = f"/{path}"
    if request.url.query:
        upstream_url += f"?{request.url.query}"

    # Build forwarded headers
    headers = {}
    for key, value in request.headers.items():
        if key.lower() not in HOP_HEADERS:
            headers[key] = value

    body = await request.body()

    try:
        resp = await _client.request(
            method=request.method,
            url=upstream_url,
            headers=headers,
            content=body if body else None,
        )
    except httpx.RequestError as exc:
        logger.error("Proxy upstream error: %s", exc)
        return Response(content=f'{{"error":"upstream unavailable"}}', status_code=502, media_type="application/json")

    # Audit the request (non-blocking best-effort)
    if path.startswith("api/"):
        await _audit(db, request.method, path, resp.status_code)

    # Build response, stripping hop headers
    resp_headers = {
        k: v
        for k, v in resp.headers.items()
        if k.lower() not in HOP_HEADERS and k.lower() != "content-encoding"
    }

    return Response(
        content=resp.content,
        status_code=resp.status_code,
        headers=resp_headers,
        media_type=resp.headers.get("content-type"),
    )
