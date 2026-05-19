"""
Verticals API — Exposes LockerSphere white-label vertical configurations.

GET /verticals           — list all available verticals
GET /verticals/{type}    — get full config for a specific vertical
GET /verticals/compare   — compare features/compliance across verticals
"""

from fastapi import APIRouter, HTTPException, Query
from typing import Optional
from apps.verticals.base import VerticalType
from apps.verticals.registry import get_vertical, list_verticals, list_vertical_types

router = APIRouter()


@router.get("/")
async def get_all_verticals():
    """List all available LockerSphere white-label verticals."""
    verticals = list_verticals()
    return {
        "verticals": [
            {
                "vertical_type": v.vertical_type.value,
                "display_name": v.display_name,
                "tagline": v.tagline,
                "icon": v.icon,
                "primary_color": v.primary_color,
                "accent_color": v.accent_color,
                "default_tier": v.default_tier,
                "modules_count": len(v.modules),
                "compliance_count": len(v.compliance_frameworks),
                "ai_capabilities_count": len(v.ai_capabilities),
                "features_count": len([f for f in v.features.values() if f]),
            }
            for v in verticals
        ],
        "available_types": list_vertical_types(),
        "total": len(verticals),
    }


@router.get("/compare")
async def compare_verticals(
    types: Optional[str] = Query(
        None,
        description="Comma-separated vertical types to compare. Omit for all.",
    ),
):
    """Compare features, compliance, and AI capabilities across verticals."""
    if types:
        type_list = [t.strip() for t in types.split(",")]
    else:
        type_list = list_vertical_types()

    comparison = []
    for type_str in type_list:
        try:
            vtype = VerticalType(type_str)
        except ValueError:
            raise HTTPException(status_code=400, detail=f"Unknown vertical: {type_str}") from None
        cfg = get_vertical(vtype)
        comparison.append({
            "vertical_type": cfg.vertical_type.value,
            "display_name": cfg.display_name,
            "security": {
                "mfa_required": cfg.security.mfa_required,
                "min_password_length": cfg.security.min_password_length,
                "session_timeout_minutes": cfg.security.session_timeout_minutes,
                "audit_log_retention_days": cfg.security.audit_log_retention_days,
                "ip_allowlist_enabled": cfg.security.ip_allowlist_enabled,
            },
            "compliance_frameworks": [f.name for f in cfg.compliance_frameworks if f.required],
            "ai_capabilities": [c.name for c in cfg.ai_capabilities if c.enabled],
            "features": {k: v for k, v in cfg.features.items() if v},
            "modules": cfg.modules,
            "rate_limit_rpm": cfg.rate_limit_rpm,
            "default_tier": cfg.default_tier,
        })

    return {"comparison": comparison, "count": len(comparison)}


@router.get("/{vertical_type}")
async def get_vertical_config(vertical_type: str):
    """Get full configuration for a specific vertical."""
    try:
        vtype = VerticalType(vertical_type)
    except ValueError:
        raise HTTPException(
            status_code=404,
            detail=f"Unknown vertical: {vertical_type}. Available: {list_vertical_types()}",
        ) from None
    cfg = get_vertical(vtype)
    return cfg.to_dict()
