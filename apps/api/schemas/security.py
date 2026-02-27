"""
Security Schemas
"""

from pydantic import BaseModel, Field
from typing import Optional, Dict, Any, List
from datetime import datetime
from enum import Enum

from db.models import ThreatType, SecurityLevel


class SecurityEventBase(BaseModel):
    """Base security event schema"""
    event_type: str
    threat_type: Optional[ThreatType] = None
    security_level: SecurityLevel = SecurityLevel.MEDIUM
    description: Optional[str] = None
    details: Optional[Dict[str, Any]] = None
    ip_address: Optional[str] = None
    user_agent: Optional[str] = None


class SecurityEventCreate(SecurityEventBase):
    """Security event creation schema"""
    user_id: Optional[str] = None
    ai_confidence: Optional[float] = None
    ai_analysis: Optional[Dict[str, Any]] = None
    ai_recommendations: Optional[Dict[str, Any]] = None


class SecurityEventResponse(SecurityEventBase):
    """Security event response schema"""
    id: str
    user_id: Optional[str] = None
    ai_confidence: Optional[float] = None
    ai_analysis: Optional[Dict[str, Any]] = None
    ai_recommendations: Optional[Dict[str, Any]] = None
    status: str
    assigned_to: Optional[str] = None
    resolution: Optional[str] = None
    created_at: datetime
    updated_at: Optional[datetime] = None
    resolved_at: Optional[datetime] = None
    
    class Config:
        from_attributes = True


class ThreatStats(BaseModel):
    """Threat statistics schema"""
    total_threats: int
    threat_types: Dict[str, int]
    severity_counts: Dict[str, int]
    recent_threats: int
    open_threats: int


class SecurityControlResponse(BaseModel):
    """Security control response schema"""
    name: str
    display_name: str
    description: str
    enabled: bool
    category: str


class SecurityDashboard(BaseModel):
    """Security dashboard schema"""
    recent_events: List[SecurityEventResponse]
    threat_stats: ThreatStats
    security_score: int


class ThreatAnalysis(BaseModel):
    """Threat analysis schema"""
    threat_type: ThreatType
    confidence: float
    risk_score: int
    recommendations: List[str]
    metadata: Dict[str, Any]


class SecurityAlert(BaseModel):
    """Security alert schema"""
    id: str
    title: str
    description: str
    severity: SecurityLevel
    alert_type: str
    status: str
    created_at: datetime
    details: Dict[str, Any]
