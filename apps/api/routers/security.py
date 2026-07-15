"""
Security Routes
"""

from fastapi import APIRouter, Depends, HTTPException, status, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_, or_, func, desc
from typing import List, Optional
from datetime import datetime, timedelta

from core.database.database import get_db
from db.models import SecurityEvent, User, ThreatType, SecurityLevel
from core.security.auth import get_current_user
from apps.api.schemas.security import SecurityEventResponse, SecurityEventCreate, ThreatStats, SecurityControlResponse

router = APIRouter()


@router.get("/events", response_model=List[SecurityEventResponse])
async def list_security_events(
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=1000),
    threat_type: Optional[ThreatType] = None,
    security_level: Optional[SecurityLevel] = None,
    status: Optional[str] = None,
    start_date: Optional[datetime] = None,
    end_date: Optional[datetime] = None,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """List security events with filtering"""
    
    # Build query
    query = select(SecurityEvent).order_by(desc(SecurityEvent.created_at))
    
    # Apply filters
    conditions = []
    
    if threat_type:
        conditions.append(SecurityEvent.threat_type == threat_type)
    
    if security_level:
        conditions.append(SecurityEvent.security_level == security_level)
    
    if status:
        conditions.append(SecurityEvent.status == status)
    
    if start_date:
        conditions.append(SecurityEvent.created_at >= start_date)
    
    if end_date:
        conditions.append(SecurityEvent.created_at <= end_date)
    
    if conditions:
        query = query.where(and_(*conditions))
    
    # Apply pagination
    query = query.offset(skip).limit(limit)
    result = await db.execute(query)
    events = result.scalars().all()
    
    return [SecurityEventResponse.from_orm(event) for event in events]


@router.get("/events/{event_id}", response_model=SecurityEventResponse)
async def get_security_event(
    event_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Get security event by ID"""
    
    event = await db.get(SecurityEvent, event_id)
    if not event:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Security event not found"
        )
    
    return SecurityEventResponse.from_orm(event)


@router.post("/events", response_model=SecurityEventResponse)
async def create_security_event(
    event_data: SecurityEventCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Create new security event"""
    
    event = SecurityEvent(
        user_id=event_data.user_id,
        event_type=event_data.event_type,
        threat_type=event_data.threat_type,
        security_level=event_data.security_level,
        description=event_data.description,
        details=event_data.details,
        ip_address=event_data.ip_address,
        user_agent=event_data.user_agent,
        ai_confidence=event_data.ai_confidence,
        ai_analysis=event_data.ai_analysis,
        ai_recommendations=event_data.ai_recommendations
    )
    
    db.add(event)
    await db.commit()
    await db.refresh(event)
    
    return SecurityEventResponse.from_orm(event)


@router.put("/events/{event_id}/assign")
async def assign_security_event(
    event_id: str,
    assigned_to: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Assign security event to user"""
    
    event = await db.get(SecurityEvent, event_id)
    if not event:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Security event not found"
        )
    
    # Check if assigned user exists
    assignee = await db.get(User, assigned_to)
    if not assignee:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Assigned user not found"
        )
    
    event.assigned_to = assigned_to
    event.updated_at = datetime.utcnow()
    await db.commit()
    
    return {"message": "Event assigned successfully"}


@router.put("/events/{event_id}/resolve")
async def resolve_security_event(
    event_id: str,
    resolution: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Resolve security event"""
    
    event = await db.get(SecurityEvent, event_id)
    if not event:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Security event not found"
        )
    
    event.status = "resolved"
    event.resolution = resolution
    event.resolved_at = datetime.utcnow()
    event.updated_at = datetime.utcnow()
    await db.commit()
    
    return {"message": "Event resolved successfully"}


@router.get("/threats/stats", response_model=ThreatStats)
async def get_threat_stats(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Get threat statistics"""
    
    # Total threats
    total_result = await db.execute(select(func.count()).select_from(SecurityEvent))
    total_threats = total_result.scalar()
    
    # Threats by type
    threat_types_result = await db.execute(
        select(SecurityEvent.threat_type, func.count())
        .group_by(SecurityEvent.threat_type)
    )
    threat_types = dict(threat_types_result.all())
    
    # Threats by severity
    severity_result = await db.execute(
        select(SecurityEvent.security_level, func.count())
        .group_by(SecurityEvent.security_level)
    )
    severity_counts = dict(severity_result.all())
    
    # Recent threats (last 24 hours)
    yesterday = datetime.utcnow() - timedelta(days=1)
    recent_result = await db.execute(
        select(func.count()).select_from(SecurityEvent)
        .where(SecurityEvent.created_at >= yesterday)
    )
    recent_threats = recent_result.scalar()
    
    # Open threats
    open_result = await db.execute(
        select(func.count()).select_from(SecurityEvent)
        .where(SecurityEvent.status == "open")
    )
    open_threats = open_result.scalar()
    
    return ThreatStats(
        total_threats=total_threats,
        threat_types=threat_types,
        severity_counts=severity_counts,
        recent_threats=recent_threats,
        open_threats=open_threats
    )


@router.get("/controls", response_model=List[SecurityControlResponse])
async def get_security_controls(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Get security controls status"""
    
    # Mock security controls (in production, these would come from database)
    controls = [
        {
            "name": "mfa_enabled",
            "display_name": "Multi-Factor Authentication",
            "description": "Require MFA for all users",
            "enabled": True,
            "category": "authentication"
        },
        {
            "name": "ai_monitoring",
            "display_name": "AI Monitoring",
            "description": "AI-powered threat detection",
            "enabled": True,
            "category": "monitoring"
        },
        {
            "name": "rate_limiting",
            "display_name": "Rate Limiting",
            "description": "Prevent brute force attacks",
            "enabled": True,
            "category": "protection"
        },
        {
            "name": "session_timeout",
            "display_name": "Session Timeout",
            "description": "Auto logout inactive users",
            "enabled": True,
            "category": "session"
        },
        {
            "name": "audit_logging",
            "display_name": "Audit Logging",
            "description": "Log all security events",
            "enabled": True,
            "category": "logging"
        },
        {
            "name": "encryption",
            "display_name": "Encryption",
            "description": "End-to-end encryption",
            "enabled": True,
            "category": "encryption"
        }
    ]
    
    return [SecurityControlResponse(**control) for control in controls]


@router.post("/controls/{control_name}")
async def toggle_security_control(
    control_name: str,
    enabled: bool,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Toggle security control"""
    
    # In production, this would update the database
    # For now, we'll just return success
    return {
        "message": f"Security control {control_name} {'enabled' if enabled else 'disabled'} successfully"
    }


@router.get("/dashboard")
async def get_security_dashboard(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Get security dashboard data"""
    
    # Get recent events
    recent_result = await db.execute(
        select(SecurityEvent)
        .order_by(desc(SecurityEvent.created_at))
        .limit(10)
    )
    recent_events = recent_result.scalars().all()
    
    # Get threat stats
    stats = await get_threat_stats(current_user, db)
    
    return {
        "recent_events": [SecurityEventResponse.from_orm(event) for event in recent_events],
        "threat_stats": stats,
        "security_score": calculate_security_score(stats)
    }


def calculate_security_score(stats: ThreatStats) -> int:
    """Calculate security score based on threat statistics"""
    
    # Base score
    score = 100
    
    # Deduct points for open threats
    score -= min(stats.open_threats * 5, 50)
    
    # Deduct points for recent threats
    score -= min(stats.recent_threats * 2, 30)
    
    # Add points for low threat volume
    if stats.total_threats < 10:
        score += 10
    elif stats.total_threats < 50:
        score += 5
    
    # Ensure score is within bounds
    return max(0, min(100, score))
