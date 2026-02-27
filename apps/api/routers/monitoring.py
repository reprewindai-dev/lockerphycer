"""
Monitoring Routes
"""

from fastapi import APIRouter, Depends, HTTPException, status, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, desc, and_
from typing import List, Optional, Dict, Any
from datetime import datetime, timedelta

from core.database.database import get_db
from db.models import User, SecurityEvent, AIRequest, SystemMetrics
from apps.api.routers.auth import get_current_user
from apps.api.schemas.monitoring import MetricsResponse, SystemHealth, ActivityStats

router = APIRouter()


@router.get("/metrics", response_model=MetricsResponse)
async def get_metrics(
    start_date: Optional[datetime] = Query(None),
    end_date: Optional[datetime] = Query(None),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Get system metrics"""
    
    # Default to last 24 hours if no dates provided
    if not start_date:
        start_date = datetime.utcnow() - timedelta(days=1)
    if not end_date:
        end_date = datetime.utcnow()
    
    # Get user metrics
    user_metrics = await get_user_metrics(db, start_date, end_date)
    
    # Get security metrics
    security_metrics = await get_security_metrics(db, start_date, end_date)
    
    # Get AI metrics
    ai_metrics = await get_ai_metrics(db, start_date, end_date)
    
    # Get system metrics
    system_metrics_data = await get_system_metrics(db, start_date, end_date)
    
    return MetricsResponse(
        user_metrics=user_metrics,
        security_metrics=security_metrics,
        ai_metrics=ai_metrics,
        system_metrics=system_metrics_data,
        period={
            "start_date": start_date,
            "end_date": end_date
        }
    )


@router.get("/health", response_model=SystemHealth)
async def get_system_health(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Get system health status"""
    
    # Check database health
    db_health = await check_database_health(db)
    
    # Check AI services health
    ai_health = await check_ai_services_health()
    
    # Calculate overall health score
    health_score = calculate_health_score(db_health, ai_health)
    
    return SystemHealth(
        status="healthy" if health_score >= 80 else "degraded",
        score=health_score,
        components={
            "database": db_health,
            "ai_services": ai_health
        },
        timestamp=datetime.utcnow()
    )


@router.get("/activity", response_model=ActivityStats)
async def get_activity_stats(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Get activity statistics"""
    
    # Get user activity
    user_activity = await get_user_activity_stats(db)
    
    # Get API activity
    api_activity = await get_api_activity_stats(db)
    
    # Get security activity
    security_activity = await get_security_activity_stats(db)
    
    return ActivityStats(
        user_activity=user_activity,
        api_activity=api_activity,
        security_activity=security_activity
    )


@router.get("/dashboard")
async def get_monitoring_dashboard(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Get monitoring dashboard data"""
    
    # Get real-time metrics
    current_metrics = await get_current_metrics(db)
    
    # Get recent alerts
    recent_alerts = await get_recent_alerts(db)
    
    # Get performance metrics
    performance_metrics = await get_performance_metrics(db)
    
    return {
        "current_metrics": current_metrics,
        "recent_alerts": recent_alerts,
        "performance_metrics": performance_metrics,
        "timestamp": datetime.utcnow()
    }


async def get_user_metrics(db: AsyncSession, start_date: datetime, end_date: datetime) -> Dict[str, Any]:
    """Get user-related metrics"""
    
    # Total users
    total_users_result = await db.execute(select(func.count()).select_from(User))
    total_users = total_users_result.scalar()
    
    # Active users (users with activity in the period)
    active_users_result = await db.execute(
        select(func.count(User.id))
        .where(User.last_activity >= start_date)
    )
    active_users = active_users_result.scalar()
    
    # New users
    new_users_result = await db.execute(
        select(func.count(User.id))
        .where(User.created_at >= start_date)
    )
    new_users = new_users_result.scalar()
    
    return {
        "total_users": total_users,
        "active_users": active_users,
        "new_users": new_users,
        "user_growth_rate": calculate_growth_rate(new_users, total_users)
    }


async def get_security_metrics(db: AsyncSession, start_date: datetime, end_date: datetime) -> Dict[str, Any]:
    """Get security-related metrics"""
    
    # Total security events
    total_events_result = await db.execute(
        select(func.count()).select_from(SecurityEvent)
        .where(SecurityEvent.created_at >= start_date)
    )
    total_events = total_events_result.scalar()
    
    # Events by severity
    severity_result = await db.execute(
        select(SecurityEvent.security_level, func.count())
        .group_by(SecurityEvent.security_level)
        .where(SecurityEvent.created_at >= start_date)
    )
    events_by_severity = dict(severity_result.all())
    
    # Open events
    open_events_result = await db.execute(
        select(func.count()).select_from(SecurityEvent)
        .where(SecurityEvent.status == "open")
    )
    open_events = open_events_result.scalar()
    
    return {
        "total_events": total_events,
        "events_by_severity": events_by_severity,
        "open_events": open_events,
        "event_rate": total_events / ((end_date - start_date).total_seconds() / 3600)  # events per hour
    }


async def get_ai_metrics(db: AsyncSession, start_date: datetime, end_date: datetime) -> Dict[str, Any]:
    """Get AI-related metrics"""
    
    # Total AI requests
    total_requests_result = await db.execute(
        select(func.count()).select_from(AIRequest)
        .where(AIRequest.created_at >= start_date)
    )
    total_requests = total_requests_result.scalar()
    
    # Completed requests
    completed_requests_result = await db.execute(
        select(func.count()).select_from(AIRequest)
        .where(
            and_(
                AIRequest.created_at >= start_date,
                AIRequest.status == "completed"
            )
        )
    )
    completed_requests = completed_requests_result.scalar()
    
    # Average processing time
    avg_time_result = await db.execute(
        select(func.avg(AIRequest.processing_time))
        .where(
            and_(
                AIRequest.created_at >= start_date,
                AIRequest.status == "completed"
            )
        )
    )
    avg_processing_time = avg_time_result.scalar() or 0
    
    # Average confidence score
    avg_confidence_result = await db.execute(
        select(func.avg(AIRequest.confidence_score))
        .where(
            and_(
                AIRequest.created_at >= start_date,
                AIRequest.status == "completed"
            )
        )
    )
    avg_confidence = avg_confidence_result.scalar() or 0
    
    return {
        "total_requests": total_requests,
        "completed_requests": completed_requests,
        "success_rate": (completed_requests / total_requests * 100) if total_requests > 0 else 0,
        "avg_processing_time": avg_processing_time,
        "avg_confidence_score": avg_confidence,
        "requests_per_hour": total_requests / ((end_date - start_date).total_seconds() / 3600)
    }


async def get_system_metrics(db: AsyncSession, start_date: datetime, end_date: datetime) -> Dict[str, Any]:
    """Get system performance metrics"""
    
    # Get CPU usage (mock data for now)
    cpu_usage = 45.2
    
    # Get memory usage (mock data for now)
    memory_usage = 67.8
    
    # Get disk usage (mock data for now)
    disk_usage = 23.4
    
    # Get network traffic (mock data for now)
    network_traffic = 1024.5  # MB/s
    
    return {
        "cpu_usage": cpu_usage,
        "memory_usage": memory_usage,
        "disk_usage": disk_usage,
        "network_traffic": network_traffic,
        "uptime": get_system_uptime()
    }


async def check_database_health(db: AsyncSession) -> Dict[str, Any]:
    """Check database health"""
    try:
        # Test database connection
        await db.execute(select(1))
        
        # Get connection pool stats (mock data)
        return {
            "status": "healthy",
            "connection_pool": {
                "active": 5,
                "idle": 15,
                "total": 20
            },
            "response_time": 0.05  # seconds
        }
    except Exception as e:
        return {
            "status": "unhealthy",
            "error": str(e),
            "response_time": None
        }


async def check_ai_services_health() -> Dict[str, Any]:
    """Check AI services health"""
    
    # Mock AI services health check
    return {
        "status": "healthy",
        "models_loaded": 3,
        "total_models": 5,
        "gpu_utilization": 23.5,
        "memory_usage": 45.2
    }


def calculate_health_score(db_health: Dict[str, Any], ai_health: Dict[str, Any]) -> int:
    """Calculate overall health score"""
    
    score = 100
    
    # Database health impact
    if db_health["status"] != "healthy":
        score -= 50
    elif db_health.get("response_time", 0) > 1.0:
        score -= 20
    
    # AI services health impact
    if ai_health["status"] != "healthy":
        score -= 30
    elif ai_health.get("gpu_utilization", 0) > 90:
        score -= 10
    
    return max(0, score)


async def get_user_activity_stats(db: AsyncSession) -> Dict[str, Any]:
    """Get user activity statistics"""
    
    # Active users in last hour
    hour_ago = datetime.utcnow() - timedelta(hours=1)
    active_hour_result = await db.execute(
        select(func.count()).select_from(User)
        .where(User.last_activity >= hour_ago)
    )
    active_last_hour = active_hour_result.scalar()
    
    # Active users in last 24 hours
    day_ago = datetime.utcnow() - timedelta(days=1)
    active_day_result = await db.execute(
        select(func.count()).select_from(User)
        .where(User.last_activity >= day_ago)
    )
    active_last_day = active_day_result.scalar()
    
    return {
        "active_last_hour": active_last_hour,
        "active_last_day": active_last_day,
        "peak_hour": 14,  # 2 PM
        "peak_day": "Tuesday"
    }


async def get_api_activity_stats(db: AsyncSession) -> Dict[str, Any]:
    """Get API activity statistics"""
    
    # Mock API stats (would come from request logs in production)
    return {
        "requests_per_second": 45.2,
        "avg_response_time": 0.234,
        "error_rate": 0.02,
        "most_popular_endpoint": "/api/v1/auth/login",
        "total_requests_today": 124567
    }


async def get_security_activity_stats(db: AsyncSession) -> Dict[str, Any]:
    """Get security activity statistics"""
    
    # Recent security events
    day_ago = datetime.utcnow() - timedelta(days=1)
    recent_events_result = await db.execute(
        select(func.count()).select_from(SecurityEvent)
        .where(SecurityEvent.created_at >= day_ago)
    )
    recent_events = recent_events_result.scalar()
    
    return {
        "events_last_24h": recent_events,
        "blocked_attempts": 234,
        "failed_logins": 45,
        "suspicious_ips": 12
    }


def calculate_growth_rate(new_count: int, total_count: int) -> float:
    """Calculate growth rate percentage"""
    if total_count == 0:
        return 0.0
    return (new_count / total_count) * 100


def get_system_uptime() -> str:
    """Get system uptime (mock data)"""
    # In production, this would get actual system uptime
    return "15 days, 7 hours, 23 minutes"


async def get_current_metrics(db: AsyncSession) -> Dict[str, Any]:
    """Get current real-time metrics"""
    
    # Get current user count
    current_users_result = await db.execute(
        select(func.count()).select_from(User)
    )
    current_users = current_users_result.scalar()
    
    # Get current active threats
    active_threats_result = await db.execute(
        select(func.count()).select_from(SecurityEvent)
        .where(SecurityEvent.status == "open")
    )
    active_threats = active_threats_result.scalar()
    
    return {
        "active_users": current_users,
        "active_threats": active_threats,
        "system_load": 45.2,
        "memory_usage": 67.8
    }


async def get_recent_alerts(db: AsyncSession) -> List[Dict[str, Any]]:
    """Get recent alerts"""
    
    # Mock alerts data
    return [
        {
            "id": "1",
            "type": "security",
            "message": "Multiple failed login attempts detected",
            "severity": "medium",
            "timestamp": datetime.utcnow() - timedelta(minutes=15)
        },
        {
            "id": "2",
            "type": "performance",
            "message": "High CPU usage detected",
            "severity": "low",
            "timestamp": datetime.utcnow() - timedelta(hours=1)
        },
        {
            "id": "3",
            "type": "ai",
            "message": "AI model performance degraded",
            "severity": "high",
            "timestamp": datetime.utcnow() - timedelta(hours=2)
        }
    ]


async def get_performance_metrics(db: AsyncSession) -> Dict[str, Any]:
    """Get performance metrics"""
    
    # Mock performance data
    return {
        "response_time_p95": 0.456,
        "throughput": 1234.5,
        "error_rate": 0.01,
        "availability": 99.95
    }
