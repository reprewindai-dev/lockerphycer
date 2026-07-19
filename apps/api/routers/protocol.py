"""
Veklom Protocol Manifest — LockerPhycer Security Gateway
Normalized schema: service, repo, role, version, base_url, health,
dependencies, auth_mode, status, capabilities, links
"""
from __future__ import annotations
from typing import Dict, Any, List
from fastapi import APIRouter, Request
from pydantic import BaseModel

router = APIRouter(tags=["Veklom Protocol"])

MANIFEST: Dict[str, Any] = {
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
        "auth",
        "rbac",
        "ai-governance",
        "security-telemetry",
        "audit-evidence",
        "wallet-billing",
        "mfa",
        "seked-compilation",
        "agent-assay"
    ],
    "links": {
        "core": "https://api.veklom.com/protocol.json",
        "cappo": "https://capi.veklom.com/protocol.json",
        "ledger": "https://pgl.veklom.com/protocol.json",
        "interlink": "https://interlink.veklom.com/protocol.json"
    }
}


class IntrospectQuery(BaseModel):
    query: str


@router.get("/protocol.json", include_in_schema=False)
async def get_protocol_manifest() -> Dict[str, Any]:
    """Veklom Protocol Manifest — self-describing capability registry."""
    return MANIFEST


@router.post("/protocol/introspect", include_in_schema=False)
async def introspect_capabilities(body: IntrospectQuery) -> Dict[str, Any]:
    """Read-only capability discovery. Returns matched capabilities, auth mode, links."""
    q = body.query.lower()
    caps: List[str] = MANIFEST["capabilities"]
    matches = [c for c in caps if q == "*" or q in c]
    return {
        "query": body.query,
        "matches": matches,
        "total": len(matches),
        "auth_mode": MANIFEST["auth_mode"],
        "links": MANIFEST["links"]
    }


@router.get("/health/dependencies", include_in_schema=False)
async def health_dependencies() -> Dict[str, Any]:
    """Dependency health check."""
    return {"status": "ok", "dependencies": {}}

@router.get("/.well-known/ai-catalog.json", include_in_schema=False)
async def get_ai_catalog() -> Dict[str, Any]:
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
