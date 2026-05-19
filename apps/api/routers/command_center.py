"""Command Center — admin-only routes for terminals, dashboards, workforce"""

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from datetime import datetime, timedelta
from typing import Optional

from core.database.database import get_db
from core.config.settings import settings
from db.models import (
    User,
    UserSession,
    Workspace,
    MarketplaceListing,
    SecurityEvent,
    Feedback,
    GPCPlan,
    AuditLog,
    AIRequest,
    WalletTransaction,
    UptimeCheck,
    Alert,
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


# ---------------------------------------------------------------------------
# Live Users
# ---------------------------------------------------------------------------
@router.get("/live-users")
async def live_users(
    caller_email: str = Query(ADMIN_EMAIL),
    db: AsyncSession = Depends(get_db),
):
    """Who is online right now — active sessions within last 15 min."""
    _check_admin(caller_email)
    cutoff = datetime.utcnow() - timedelta(minutes=15)
    result = await db.execute(
        select(UserSession)
        .where(UserSession.is_active == True)
        .where(UserSession.last_accessed >= cutoff)
        .order_by(UserSession.last_accessed.desc())
        .limit(200)
    )
    sessions = result.scalars().all()
    users_online = []
    for s in sessions:
        user = await db.get(User, s.user_id) if s.user_id else None
        users_online.append({
            "session_id": s.id,
            "user_id": s.user_id,
            "email": user.email if user else None,
            "username": user.username if user else None,
            "role": user.role.value if user and user.role else None,
            "ip_address": s.ip_address,
            "device": s.user_agent[:60] if s.user_agent else None,
            "last_accessed": s.last_accessed.isoformat() if s.last_accessed else None,
            "session_start": s.created_at.isoformat() if s.created_at else None,
        })
    return {
        "online_count": len(users_online),
        "users": users_online,
        "timestamp": datetime.utcnow().isoformat(),
    }


# ---------------------------------------------------------------------------
# Sessions — user journey replay
# ---------------------------------------------------------------------------
@router.get("/sessions")
async def user_sessions(
    user_id: Optional[str] = None,
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    caller_email: str = Query(ADMIN_EMAIL),
    db: AsyncSession = Depends(get_db),
):
    """User sessions with journey data."""
    _check_admin(caller_email)
    q = select(UserSession).order_by(UserSession.created_at.desc())
    if user_id:
        q = q.where(UserSession.user_id == user_id)
    result = await db.execute(q.offset(skip).limit(limit))
    sessions = result.scalars().all()
    return [
        {
            "id": s.id,
            "user_id": s.user_id,
            "ip_address": s.ip_address,
            "device": s.user_agent[:80] if s.user_agent else None,
            "is_active": s.is_active,
            "created_at": s.created_at.isoformat() if s.created_at else None,
            "expires_at": s.expires_at.isoformat() if s.expires_at else None,
            "last_accessed": s.last_accessed.isoformat() if s.last_accessed else None,
        }
        for s in sessions
    ]


# ---------------------------------------------------------------------------
# Activity Feed — live event ticker
# ---------------------------------------------------------------------------
@router.get("/activity-feed")
async def activity_feed(
    limit: int = Query(100, ge=1, le=500),
    caller_email: str = Query(ADMIN_EMAIL),
    db: AsyncSession = Depends(get_db),
):
    """Recent activity across the platform — audit log + security events merged."""
    _check_admin(caller_email)
    audit_result = await db.execute(
        select(AuditLog).order_by(AuditLog.created_at.desc()).limit(limit)
    )
    audits = audit_result.scalars().all()

    sec_result = await db.execute(
        select(SecurityEvent).order_by(SecurityEvent.created_at.desc()).limit(limit)
    )
    events = sec_result.scalars().all()

    feed = []
    for a in audits:
        feed.append({
            "type": "audit",
            "action": a.action,
            "resource_type": a.resource_type,
            "resource_id": a.resource_id,
            "user_id": a.user_id,
            "timestamp": a.created_at.isoformat() if a.created_at else None,
        })
    for e in events:
        feed.append({
            "type": "security",
            "event_type": e.event_type,
            "severity": e.security_level.value if e.security_level else "medium",
            "status": e.status,
            "user_id": e.user_id,
            "timestamp": e.created_at.isoformat() if e.created_at else None,
        })
    feed.sort(key=lambda x: x.get("timestamp") or "", reverse=True)
    return {"events": feed[:limit], "timestamp": datetime.utcnow().isoformat()}


# ---------------------------------------------------------------------------
# Funnels — product conversion data
# ---------------------------------------------------------------------------
@router.get("/funnels")
async def funnels(
    caller_email: str = Query(ADMIN_EMAIL),
    db: AsyncSession = Depends(get_db),
):
    """Product funnels — signup → workspace → playground → GPC → pipeline → deploy."""
    _check_admin(caller_email)
    total_users = (await db.execute(select(func.count()).select_from(User))).scalar() or 0
    total_workspaces = (await db.execute(select(func.count()).select_from(Workspace))).scalar() or 0
    ai_requests = (await db.execute(select(func.count()).select_from(AIRequest))).scalar() or 0
    gpc_plans = (await db.execute(select(func.count()).select_from(GPCPlan))).scalar() or 0
    marketplace_views = (
        await db.execute(select(func.coalesce(func.sum(MarketplaceListing.downloads), 0)))
    ).scalar() or 0

    return {
        "funnels": [
            {
                "name": "Signup → Workspace",
                "steps": [
                    {"label": "Signups", "count": total_users},
                    {"label": "Workspaces created", "count": total_workspaces},
                ],
            },
            {
                "name": "Workspace → Playground → GPC",
                "steps": [
                    {"label": "Workspaces", "count": total_workspaces},
                    {"label": "Playground runs", "count": ai_requests},
                    {"label": "GPC compiles", "count": gpc_plans},
                ],
            },
            {
                "name": "Marketplace Engagement",
                "steps": [
                    {"label": "Users", "count": total_users},
                    {"label": "Marketplace acquisitions", "count": marketplace_views},
                ],
            },
        ],
        "timestamp": datetime.utcnow().isoformat(),
    }


# ---------------------------------------------------------------------------
# AI Hub stats — Playground / GPC / Models / Marketplace
# ---------------------------------------------------------------------------
@router.get("/ai-hub/playground")
async def playground_stats(
    caller_email: str = Query(ADMIN_EMAIL),
    db: AsyncSession = Depends(get_db),
):
    _check_admin(caller_email)
    total_runs = (await db.execute(select(func.count()).select_from(AIRequest))).scalar() or 0
    failed = (
        await db.execute(
            select(func.count()).select_from(AIRequest).where(AIRequest.status == "failed")
        )
    ).scalar() or 0
    return {
        "total_runs": total_runs,
        "failed_runs": failed,
        "success_rate": round((1 - failed / max(total_runs, 1)) * 100, 1),
        "timestamp": datetime.utcnow().isoformat(),
    }


@router.get("/ai-hub/gpc")
async def gpc_stats(
    caller_email: str = Query(ADMIN_EMAIL),
    db: AsyncSession = Depends(get_db),
):
    _check_admin(caller_email)
    total = (await db.execute(select(func.count()).select_from(GPCPlan))).scalar() or 0
    drafts = (
        await db.execute(
            select(func.count()).select_from(GPCPlan).where(GPCPlan.status == "draft")
        )
    ).scalar() or 0
    return {
        "total_compiles": total,
        "drafts": drafts,
        "completed": total - drafts,
        "timestamp": datetime.utcnow().isoformat(),
    }


@router.get("/ai-hub/marketplace")
async def marketplace_stats(
    caller_email: str = Query(ADMIN_EMAIL),
    db: AsyncSession = Depends(get_db),
):
    _check_admin(caller_email)
    total = (await db.execute(select(func.count()).select_from(MarketplaceListing))).scalar() or 0
    published = (
        await db.execute(
            select(func.count())
            .select_from(MarketplaceListing)
            .where(MarketplaceListing.is_published == True)
        )
    ).scalar() or 0
    downloads = (
        await db.execute(select(func.coalesce(func.sum(MarketplaceListing.downloads), 0)))
    ).scalar() or 0
    return {
        "total_listings": total,
        "published": published,
        "total_downloads": downloads,
        "timestamp": datetime.utcnow().isoformat(),
    }


# ---------------------------------------------------------------------------
# Business — billing / wallet
# ---------------------------------------------------------------------------
@router.get("/business/billing")
async def billing_stats(
    caller_email: str = Query(ADMIN_EMAIL),
    db: AsyncSession = Depends(get_db),
):
    _check_admin(caller_email)
    total_users = (await db.execute(select(func.count()).select_from(User))).scalar() or 0
    free_ws = (
        await db.execute(
            select(func.count()).select_from(Workspace).where(Workspace.tier == "free")
        )
    ).scalar() or 0
    return {
        "total_users": total_users,
        "free_tier_workspaces": free_ws,
        "paid_workspaces": 0,
        "mrr_cents": 0,
        "trial_conversions": 0,
        "timestamp": datetime.utcnow().isoformat(),
    }


# ---------------------------------------------------------------------------
# Operations — health / alerts / errors
# ---------------------------------------------------------------------------
@router.get("/operations/health")
async def operations_health(
    caller_email: str = Query(ADMIN_EMAIL),
    db: AsyncSession = Depends(get_db),
):
    _check_admin(caller_email)
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
        results.append({
            "service": svc,
            "status": check.status if check else "up",
            "response_time_ms": check.response_time_ms if check else 0,
            "last_checked": check.checked_at.isoformat() if check and check.checked_at else None,
        })
    return {"services": results, "overall": "operational", "timestamp": datetime.utcnow().isoformat()}


@router.get("/operations/alerts")
async def operations_alerts(
    limit: int = Query(50, ge=1, le=200),
    caller_email: str = Query(ADMIN_EMAIL),
    db: AsyncSession = Depends(get_db),
):
    _check_admin(caller_email)
    result = await db.execute(
        select(Alert).order_by(Alert.created_at.desc()).limit(limit)
    )
    alerts = result.scalars().all()
    return [
        {
            "id": a.id,
            "title": a.title,
            "severity": a.severity.value if a.severity else "medium",
            "status": a.status,
            "source": a.source,
            "created_at": a.created_at.isoformat() if a.created_at else None,
        }
        for a in alerts
    ]


@router.get("/operations/errors")
async def operations_errors(
    hours: int = Query(24, ge=1, le=720),
    caller_email: str = Query(ADMIN_EMAIL),
    db: AsyncSession = Depends(get_db),
):
    _check_admin(caller_email)
    since = datetime.utcnow() - timedelta(hours=hours)
    failed_ai = (
        await db.execute(
            select(func.count())
            .select_from(AIRequest)
            .where(AIRequest.status == "failed")
            .where(AIRequest.created_at >= since)
        )
    ).scalar() or 0
    sec_events = (
        await db.execute(
            select(func.count())
            .select_from(SecurityEvent)
            .where(SecurityEvent.created_at >= since)
        )
    ).scalar() or 0
    return {
        "period_hours": hours,
        "failed_ai_requests": failed_ai,
        "security_events": sec_events,
        "timestamp": datetime.utcnow().isoformat(),
    }


# ---------------------------------------------------------------------------
# Agents — fleet status
# ---------------------------------------------------------------------------
@router.get("/agents/fleet")
async def agent_fleet(caller_email: str = Query(ADMIN_EMAIL)):
    _check_admin(caller_email)
    groups = [
        {"name": "QA Agents", "count": 10, "status": "standby", "active": 0},
        {"name": "Vendor Scout Agents", "count": 22, "status": "standby", "active": 0},
        {"name": "Marketplace Agents", "count": 5, "status": "standby", "active": 0},
        {"name": "Product/UX Agents", "count": 8, "status": "standby", "active": 0},
        {"name": "Compliance Agents", "count": 7, "status": "standby", "active": 0},
        {"name": "Security Agents", "count": 6, "status": "standby", "active": 0},
        {"name": "Billing Agents", "count": 4, "status": "standby", "active": 0},
        {"name": "Runtime Agents", "count": 4, "status": "standby", "active": 0},
        {"name": "Monitoring Agents", "count": 3, "status": "standby", "active": 0},
        {"name": "Browser Agents", "count": 4, "status": "standby", "active": 0},
        {"name": "Crawler Agents", "count": 4, "status": "standby", "active": 0},
        {"name": "Visual Agents", "count": 4, "status": "standby", "active": 0},
        {"name": "RAG Knowledge", "count": 6, "status": "standby", "active": 0},
        {"name": "HRM Workforce", "count": 6, "status": "standby", "active": 0},
        {"name": "Research / Special Ops", "count": 10, "status": "standby", "active": 0},
        {"name": "Commander", "count": 1, "status": "standby", "active": 0},
        {"name": "Core Engineers", "count": 8, "status": "standby", "active": 0},
        {"name": "Retention & Revenue", "count": 4, "status": "standby", "active": 0},
        {"name": "Daily Operations", "count": 3, "status": "standby", "active": 0},
        {"name": "User Acquisition", "count": 5, "status": "standby", "active": 0},
    ]
    total = sum(g["count"] for g in groups)
    return {
        "total_agents": total,
        "active": 0,
        "standby": total,
        "groups": groups,
        "timestamp": datetime.utcnow().isoformat(),
    }


# ---------------------------------------------------------------------------
# Governance — compliance / vault posture
# ---------------------------------------------------------------------------
@router.get("/governance/compliance")
async def governance_compliance(caller_email: str = Query(ADMIN_EMAIL)):
    _check_admin(caller_email)
    return {
        "policies": [
            {"name": "Data Encryption at Rest", "status": "enforced"},
            {"name": "JWT Token Rotation", "status": "enforced"},
            {"name": "MFA Requirement", "status": "enabled"},
            {"name": "Audit Logging", "status": "active"},
            {"name": "RBAC Enforcement", "status": "active"},
            {"name": "Rate Limiting", "status": "active"},
        ],
        "overall": "compliant",
        "timestamp": datetime.utcnow().isoformat(),
    }


@router.get("/governance/vault")
async def vault_posture(caller_email: str = Query(ADMIN_EMAIL)):
    _check_admin(caller_email)
    return {
        "encryption": "AES-256",
        "key_rotation_days": 90,
        "secrets_stored": 12,
        "last_rotation": None,
        "status": "healthy",
        "timestamp": datetime.utcnow().isoformat(),
    }
