"""
Veklom Protocol Manifest — LockerPhycer Security Gateway
Normalized schema: service, repo, role, version, base_url, health,
dependencies, auth_mode, status, capabilities, links
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter
from pydantic import BaseModel

router = APIRouter(tags=["Veklom Protocol"])

MANIFEST: dict[str, Any] = {
    "service": "lockerphycer",
    "repo": "reprewindai-dev/lockerphycer",
    "role": "security-control-plane",
    "version": "2026.07",
    "base_url": "https://command.veklom.com",
    "health": "/health",
    "dependencies": "/health/dependencies",
    "auth_mode": "bearer",
    "status": "ok",
    "capabilities": [
        "authenticate_users",
        "retrieve_current_identity",
        "register_users",
        "inspect_agent_identity",
    ],
    "capability_endpoints": {
        "authenticate_users": "POST /api/v1/auth/login",
        "retrieve_current_identity": "GET /api/v1/auth/me",
        "register_users": "POST /api/v1/auth/register",
        "inspect_agent_identity": "GET /api/v1/agents/registry/{agent_number}",
    },
    "links": {
        "lockerphycer": "https://command.veklom.com/protocol.json",
        "byos": "https://api.veklom.com/protocol.json",
        "capi": "https://capi.veklom.com/protocol.json",
        "cappo": "https://cappo.veklom.com/protocol.json",
        "pgl": "https://pgl.veklom.com/protocol.json",
        "core": "https://api.veklom.com/protocol.json",
        "ledger": "https://pgl.veklom.com/protocol.json",
        "interlink": "https://capi.veklom.com/protocol.json",
    },
}


class IntrospectQuery(BaseModel):
    query: str


@router.get("/protocol.json", include_in_schema=False)
async def get_protocol_manifest() -> dict[str, Any]:
    """Veklom Protocol Manifest — self-describing capability registry."""
    return MANIFEST


@router.post("/protocol/introspect", include_in_schema=False)
async def introspect_capabilities(body: IntrospectQuery) -> dict[str, Any]:
    """Read-only capability discovery. Returns matched capabilities, auth mode, links."""
    q = body.query.lower()
    caps: list[str] = MANIFEST["capabilities"]
    matches = [c for c in caps if q == "*" or q in c]
    return {
        "query": body.query,
        "matches": matches,
        "total": len(matches),
        "auth_mode": MANIFEST["auth_mode"],
        "links": MANIFEST["links"],
    }

@router.get("/.well-known/ai-catalog.json", include_in_schema=False)
async def get_ai_catalog() -> dict[str, Any]:
    """
    Agentic Resource Discovery (ARD) Catalog (Layer 2)
    Provides a standardized machine-readable catalog of all API capabilities.
    """
    return {
        "catalog_version": "1.0",
        "provider": MANIFEST["service"],
        "endpoints": [
            {
                "path": "/api/v1/compiler/compile",
                "description": "SEKED Compiler for deterministic planning",
                "method": "POST"
            },
            {
                "path": "/api/v1/actors/{actor_id}/run",
                "description": "Execute agent with CAPPO and PGL enforcement",
                "method": "POST"
            }
        ],
        "authentication": MANIFEST["auth_mode"]
    }
