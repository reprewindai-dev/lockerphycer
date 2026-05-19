"""Marketplace catalog — exports LockerSphere verticals for the Veklom Marketplace.

Each vertical is exposed as a structured listing payload that the Veklom
Marketplace auto-classify / auto-validate pipeline can ingest directly.
"""

from fastapi import APIRouter

from apps.verticals.registry import VerticalRegistry

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


@router.get("/catalog")
async def catalog():
    """Return all verticals formatted as Veklom Marketplace listing payloads.

    Each entry is compatible with the ``POST /marketplace/auto-classify``
    and ``POST /marketplace/auto-validate`` automation endpoints on veklom.com.
    """
    registry = VerticalRegistry()
    listings = []

    for key, vertical in registry.verticals.items():
        config = vertical.get_config()
        listings.append({
            "slug": f"lockersphere-{key}",
            "title": config["name"],
            "description": config["description"],
            "listing_type": "agent",
            "category": _category_for(key),
            "tags": _tags_for(key, config),
            "compliance_badges": config.get("compliance_frameworks", []),
            "price_cents": _VERTICAL_PRICES.get(key, 0),
            "currency": "usd",
            "tier": _VERTICAL_TIERS.get(key, "standard"),
            "install_payload": {
                "type": "lockersphere_vertical",
                "vertical_key": key,
                "security_policy": config.get("security_policy", {}),
                "ai_capabilities": [c["name"] for c in config.get("ai_capabilities", [])],
                "features": [f["name"] for f in config.get("features", [])],
                "compliance_frameworks": config.get("compliance_frameworks", []),
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
    registry = VerticalRegistry()
    vertical = registry.get_vertical(vertical_key)
    if not vertical:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail=f"Vertical '{vertical_key}' not found")

    config = vertical.get_config()
    return {
        "slug": f"lockersphere-{vertical_key}",
        "title": config["name"],
        "description": config["description"],
        "listing_type": "agent",
        "category": _category_for(vertical_key),
        "tags": _tags_for(vertical_key, config),
        "compliance_badges": config.get("compliance_frameworks", []),
        "price_cents": _VERTICAL_PRICES.get(vertical_key, 0),
        "currency": "usd",
        "tier": _VERTICAL_TIERS.get(vertical_key, "standard"),
        "install_payload": {
            "type": "lockersphere_vertical",
            "vertical_key": vertical_key,
            "security_policy": config.get("security_policy", {}),
            "ai_capabilities": [c["name"] for c in config.get("ai_capabilities", [])],
            "features": [f["name"] for f in config.get("features", [])],
            "compliance_frameworks": config.get("compliance_frameworks", []),
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
