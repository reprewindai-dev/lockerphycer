"""Marketplace catalog — exports LockerSphere verticals for the Veklom Marketplace.

Each vertical is exposed as a structured listing payload that the Veklom
Marketplace auto-classify / auto-validate pipeline can ingest directly.
"""

from fastapi import APIRouter, HTTPException

from apps.verticals.registry import list_verticals, get_vertical
from apps.verticals.base import VerticalType

router = APIRouter(prefix="/marketplace", tags=["marketplace-catalog"])

_VERTICAL_PRICES = {
    "hospital": 0,       # enterprise — contact sales
    "bank": 0,           # enterprise — contact sales
    "insurance": 0,      # enterprise — contact sales
    "content_creator": 0,  # free tier
    "general": 0,        # free tier
}

_VERTICAL_TIERS = {
    "hospital": "enterprise",
    "bank": "enterprise",
    "insurance": "enterprise",
    "content_creator": "standard",
    "general": "standard",
}


def _config_to_dict(cfg) -> dict:
    """Convert a VerticalConfig to a dict safely."""
    if hasattr(cfg, "to_dict"):
        return cfg.to_dict()
    if isinstance(cfg, dict):
        return cfg
    return {}


@router.get("/catalog")
async def catalog():
    """Return all verticals formatted as Veklom Marketplace listing payloads."""
    verticals = list_verticals()
    listings = []

    for vertical in verticals:
        config = _config_to_dict(vertical)
        key = config.get("vertical_type", "general")
        listings.append({
            "slug": f"lockersphere-{key}",
            "title": config.get("display_name", key),
            "description": config.get("description", ""),
            "listing_type": "agent",
            "category": _category_for(key),
            "tags": _tags_for(key, config),
            "compliance_badges": [
                f.get("name", "") if isinstance(f, dict) else str(f)
                for f in config.get("compliance_frameworks", [])
            ],
            "price_cents": _VERTICAL_PRICES.get(key, 0),
            "currency": "usd",
            "tier": _VERTICAL_TIERS.get(key, "standard"),
            "install_payload": {
                "type": "lockersphere_vertical",
                "vertical_key": key,
                "security_policy": config.get("security", {}),
                "ai_capabilities": [
                    c.get("name", "") if isinstance(c, dict) else str(c)
                    for c in config.get("ai_capabilities", [])
                ],
                "features": list(config.get("features", {}).keys()) if isinstance(config.get("features"), dict) else [],
                "compliance_frameworks": [
                    f.get("name", "") if isinstance(f, dict) else str(f)
                    for f in config.get("compliance_frameworks", [])
                ],
                "rate_limit_rpm": config.get("rate_limit_rpm", 100),
            },
            "source_url": "https://github.com/reprewindai-dev/lockerphycer",
            "use_url": f"/api/v1/verticals/{key}",
        })

    return {
        "provider": "LockerSphere",
        "version": "1.0.0",
        "listing_count": len(listings),
        "listings": listings,
    }


@router.get("/catalog/{vertical_key}")
async def catalog_detail(vertical_key: str):
    """Return a single vertical as a Veklom Marketplace listing payload."""
    try:
        vtype = VerticalType(vertical_key)
        vertical = get_vertical(vtype)
    except (KeyError, ValueError):
        raise HTTPException(status_code=404, detail=f"Vertical '{vertical_key}' not found")

    config = _config_to_dict(vertical)
    key = config.get("vertical_type", vertical_key)
    return {
        "slug": f"lockersphere-{key}",
        "title": config.get("display_name", key),
        "description": config.get("description", ""),
        "listing_type": "agent",
        "category": _category_for(key),
        "tags": _tags_for(key, config),
        "compliance_badges": [
            f.get("name", "") if isinstance(f, dict) else str(f)
            for f in config.get("compliance_frameworks", [])
        ],
        "price_cents": _VERTICAL_PRICES.get(key, 0),
        "currency": "usd",
        "tier": _VERTICAL_TIERS.get(key, "standard"),
        "install_payload": {
            "type": "lockersphere_vertical",
            "vertical_key": key,
            "security_policy": config.get("security", {}),
            "ai_capabilities": [
                c.get("name", "") if isinstance(c, dict) else str(c)
                for c in config.get("ai_capabilities", [])
            ],
            "features": list(config.get("features", {}).keys()) if isinstance(config.get("features"), dict) else [],
            "compliance_frameworks": [
                f.get("name", "") if isinstance(f, dict) else str(f)
                for f in config.get("compliance_frameworks", [])
            ],
            "rate_limit_rpm": config.get("rate_limit_rpm", 100),
        },
        "source_url": "https://github.com/reprewindai-dev/lockerphycer",
        "use_url": f"/api/v1/verticals/{vertical_key}",
    }


def _category_for(key: str) -> str:
    return {
        "hospital": "medical",
        "bank": "finance",
        "insurance": "finance",
        "content_creator": "agency",
        "general": "general",
    }.get(key, "general")


def _tags_for(key: str, config: dict) -> list[str]:
    base = ["lockersphere", "ai-security", "white-label"]
    extra = {
        "hospital": ["hipaa", "healthcare", "phi-protection", "clinical-ai"],
        "bank": ["pci-dss", "banking", "fraud-detection", "aml-kyc"],
        "insurance": ["solvency-ii", "claims-fraud", "actuarial", "underwriting"],
        "content_creator": ["dmca", "content-moderation", "deepfake-detection", "creator"],
        "general": ["soc2", "threat-detection", "anomaly-detection"],
    }
    return base + extra.get(key, [])
