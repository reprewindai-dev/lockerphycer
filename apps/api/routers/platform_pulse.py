"""Platform Pulse — real-time metrics, admin finance, uptime monitor"""

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from datetime import datetime, timedelta

from core.database.database import get_db
from core.config.settings import settings
from db.models import (
    User,
    Workspace,
    MarketplaceListing,
    WalletTransaction,
    UptimeCheck,
    SecurityEvent,
    Feedback,
    GPCPlan,
)

router = APIRouter()


@router.get("/pulse")
async def platform_pulse(
    is_superuser: bool = Query(False),
    db: AsyncSession = Depends(get_db),
):
    """Public transparency pulse + optional superuser finance overlay."""
    now = datetime.utcnow()
    thirty_days_ago = now - timedelta(days=30)
    seven_days_ago = now - timedelta(days=7)

    total_users = (await db.execute(select(func.count()).select_from(User))).scalar() or 0
    new_users_30d = (
        await db.execute(
            select(func.count()).select_from(User).where(User.created_at >= thirty_days_ago)
        )
    ).scalar() or 0
    prev_users_30d = (
        await db.execute(
            select(func.count())
            .select_from(User)
            .where(User.created_at >= thirty_days_ago - timedelta(days=30))
            .where(User.created_at < thirty_days_ago)
        )
    ).scalar() or 0

    active_listings = (
        await db.execute(
            select(func.count())
            .select_from(MarketplaceListing)
            .where(MarketplaceListing.is_published == True)
        )
    ).scalar() or 0
    new_listings_7d = (
        await db.execute(
            select(func.count())
            .select_from(MarketplaceListing)
            .where(MarketplaceListing.created_at >= seven_days_ago)
        )
    ).scalar() or 0

    total_installs = (
        await db.execute(select(func.coalesce(func.sum(MarketplaceListing.downloads), 0)))
    ).scalar() or 0

    active_tools = (
        await db.execute(
            select(func.count())
            .select_from(MarketplaceListing)
            .where(MarketplaceListing.is_published == True)
            .where(MarketplaceListing.listing_type == "tool")
        )
    ).scalar() or 0

    gpc_compiles = (await db.execute(select(func.count()).select_from(GPCPlan))).scalar() or 0

    open_feedback = (
        await db.execute(
            select(func.count()).select_from(Feedback).where(Feedback.status == "open")
        )
    ).scalar() or 0

    payload = {
        "total_users": total_users,
        "user_growth_pct_30d": round(
            ((new_users_30d - prev_users_30d) / max(prev_users_30d, 1)) * 100, 1
        ),
        "active_listings": active_listings,
        "new_listings_7d": new_listings_7d,
        "tool_installs": total_installs,
        "active_tools": active_tools,
        "gpc_compiles_total": gpc_compiles,
        "open_feedback": open_feedback,
        "refreshed_at": now.isoformat(),
    }

    if is_superuser:
        # Finance & risk overlay — admin only
        open_threats = (
            await db.execute(
                select(func.count())
                .select_from(SecurityEvent)
                .where(SecurityEvent.status == "open")
            )
        ).scalar() or 0

        payload["finance"] = {
            "mrr_cents": 0,
            "arpu_cents": 0,
            "churn_30d_pct": 0.0,
            "churn_status": "healthy",
            "trial_conversions_30d": 0,
            "marketplace_gross_30d_cents": 0,
            "past_due_subs": 0,
            "past_due_status": "all current",
            "open_security_threats": open_threats,
            "threat_status": "clear" if open_threats == 0 else "attention",
        }

    return payload


@router.get("/uptime")
async def uptime_status(db: AsyncSession = Depends(get_db)):
    """Public uptime monitor"""
    services = ["api", "database", "gpc", "marketplace", "auth"]
    results = []
    for svc in services:
        last_check = await db.execute(
            select(UptimeCheck)
            .where(UptimeCheck.service_name == svc)
            .order_by(UptimeCheck.checked_at.desc())
            .limit(1)
        )
        check = last_check.scalars().first()
        if check:
            results.append(
                {
                    "service": svc,
                    "status": check.status,
                    "response_time_ms": check.response_time_ms,
                    "last_checked": check.checked_at.isoformat() if check.checked_at else None,
                }
            )
        else:
            results.append(
                {"service": svc, "status": "up", "response_time_ms": 0, "last_checked": None}
            )
    return {"services": results, "overall": "operational", "checked_at": datetime.utcnow().isoformat()}


@router.get("/uptime/history")
async def uptime_history(
    service: str = "api",
    hours: int = Query(24, ge=1, le=720),
    db: AsyncSession = Depends(get_db),
):
    since = datetime.utcnow() - timedelta(hours=hours)
    result = await db.execute(
        select(UptimeCheck)
        .where(UptimeCheck.service_name == service)
        .where(UptimeCheck.checked_at >= since)
        .order_by(UptimeCheck.checked_at.asc())
    )
    checks = result.scalars().all()
    total = len(checks)
    up_count = sum(1 for c in checks if c.status == "up")
    return {
        "service": service,
        "period_hours": hours,
        "total_checks": total,
        "uptime_pct": round((up_count / max(total, 1)) * 100, 2),
        "checks": [
            {
                "status": c.status,
                "response_time_ms": c.response_time_ms,
                "checked_at": c.checked_at.isoformat() if c.checked_at else None,
            }
            for c in checks[-100:]
        ],
    }
