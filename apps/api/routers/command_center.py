"""Command Center — admin-only routes for terminals, dashboards, workforce"""

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from datetime import datetime, timedelta

from core.database.database import get_db
from core.config.settings import settings
from db.models import (
    User,
    Workspace,
    MarketplaceListing,
    SecurityEvent,
    Feedback,
    GPCPlan,
    AuditLog,
)

router = APIRouter()

ADMIN_EMAIL = settings.ADMIN_EMAIL


def _check_admin(caller_email: str):
    if caller_email != ADMIN_EMAIL:
        raise HTTPException(status_code=403, detail="Command Center: admin only")


@router.get("/overview")
async def command_overview(
    caller_email: str = Query(ADMIN_EMAIL),
    db: AsyncSession = Depends(get_db),
):
    """Admin overview dashboard with users, listings, orders, finance"""
    _check_admin(caller_email)
    now = datetime.utcnow()
    thirty_days = now - timedelta(days=30)

    total_users = (await db.execute(select(func.count()).select_from(User))).scalar() or 0
    active_listings = (
        await db.execute(
            select(func.count())
            .select_from(MarketplaceListing)
            .where(MarketplaceListing.is_published == True)
        )
    ).scalar() or 0
    total_installs = (
        await db.execute(select(func.coalesce(func.sum(MarketplaceListing.downloads), 0)))
    ).scalar() or 0
    gpc_plans = (await db.execute(select(func.count()).select_from(GPCPlan))).scalar() or 0
    open_feedback = (
        await db.execute(
            select(func.count()).select_from(Feedback).where(Feedback.status == "open")
        )
    ).scalar() or 0
    open_threats = (
        await db.execute(
            select(func.count()).select_from(SecurityEvent).where(SecurityEvent.status == "open")
        )
    ).scalar() or 0

    return {
        "users": {"total": total_users},
        "listings": {"active": active_listings, "installs": total_installs},
        "gpc": {"total_plans": gpc_plans},
        "feedback": {"open": open_feedback},
        "security": {"open_threats": open_threats, "status": "clear" if open_threats == 0 else "attention"},
        "finance": {
            "mrr_cents": 0,
            "arpu_cents": 0,
            "churn_30d_pct": 0.0,
            "trial_conversions_30d": 0,
            "marketplace_gross_30d_cents": 0,
            "past_due_subs": 0,
        },
        "timestamp": now.isoformat(),
    }


@router.get("/terminals/quantum")
async def quantum_terminal_config(caller_email: str = Query(ADMIN_EMAIL)):
    """Return config for the UACP Quantum Terminal (admin-only)"""
    _check_admin(caller_email)
    return {
        "terminal": "uacp-quantum-terminal",
        "version": "1.0.0",
        "endpoints": {
            "plans": "/api/v1/gpc/plans",
            "compile": "/api/v1/gpc/compile",
            "execute": "/api/v1/gpc/plans/{plan_id}/execute",
            "events": "/api/v1/monitoring/activity",
            "signals": "/api/v1/platform/pulse",
            "security": "/api/v1/security/events",
            "users": "/api/v1/users/",
            "workspaces": "/api/v1/workspace/",
            "marketplace": "/api/v1/marketplace/listings",
        },
        "websocket": "/ws/terminal",
        "admin_email": ADMIN_EMAIL,
    }


@router.get("/terminals/veklom")
async def veklom_terminal_config(caller_email: str = Query(ADMIN_EMAIL)):
    """Return config for the Veklom Terminal / remix-uacp-quantum-context (admin-only)"""
    _check_admin(caller_email)
    return {
        "terminal": "veklom-terminal",
        "version": "1.0.0",
        "endpoints": {
            "overview": "/api/v1/command-center/overview",
            "pulse": "/api/v1/platform/pulse?is_superuser=true",
            "gpc_stats": "/api/v1/gpc/stats",
            "uptime": "/api/v1/platform/uptime",
            "feedback": "/api/v1/feedback/",
            "security_events": "/api/v1/security/events",
            "monitoring": "/api/v1/monitoring/dashboard",
            "ai_models": "/api/v1/ai/models",
            "billing_pricing": "/api/v1/billing/pricing",
        },
        "websocket": "/ws/terminal",
        "admin_email": ADMIN_EMAIL,
    }


@router.get("/workforce/status")
async def workforce_status(caller_email: str = Query(ADMIN_EMAIL)):
    """120-agent workforce status (admin-only)"""
    _check_admin(caller_email)
    agents = []
    categories = [
        ("Commander", 0, 0),
        ("Core Engineers", 1, 8),
        ("Vendor Acquisition", 10, 31),
        ("User Acquisition", 40, 44),
        ("Retention & Revenue", 50, 53),
        ("Daily Operations", 60, 62),
        ("Research / Special Ops", 63, 72),
        ("Governance & Compliance", 73, 79),
        ("QA & Testing", 80, 89),
        ("Browser Agents", 90, 93),
        ("Crawler Agents", 94, 97),
        ("Visual Agents", 98, 101),
        ("Security Force", 102, 107),
        ("RAG Knowledge", 108, 113),
        ("HRM Workforce", 114, 119),
    ]
    for cat, start, end in categories:
        agents.append(
            {
                "category": cat,
                "range": f"{start:03d}-{end:03d}",
                "count": end - start + 1,
                "status": "standby",
                "active": 0,
            }
        )
    return {
        "total_agents": 120,
        "active": 0,
        "standby": 120,
        "categories": agents,
        "timestamp": datetime.utcnow().isoformat(),
    }


@router.get("/audit-log")
async def get_audit_log(
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    caller_email: str = Query(ADMIN_EMAIL),
    db: AsyncSession = Depends(get_db),
):
    _check_admin(caller_email)
    result = await db.execute(
        select(AuditLog).order_by(AuditLog.created_at.desc()).offset(skip).limit(limit)
    )
    logs = result.scalars().all()
    return [
        {
            "id": l.id,
            "user_id": l.user_id,
            "action": l.action,
            "resource_type": l.resource_type,
            "resource_id": l.resource_id,
            "created_at": l.created_at.isoformat() if l.created_at else None,
        }
        for l in logs
    ]
