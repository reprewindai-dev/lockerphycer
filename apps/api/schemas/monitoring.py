"""
Monitoring Schemas
"""

from pydantic import BaseModel, Field
from typing import Dict, Any, Optional
from datetime import datetime


class MetricsResponse(BaseModel):
    """Metrics response schema"""
    user_metrics: Dict[str, Any]
    security_metrics: Dict[str, Any]
    ai_metrics: Dict[str, Any]
    system_metrics: Dict[str, Any]
    period: Dict[str, datetime]


class SystemHealth(BaseModel):
    """System health schema"""
    status: str
    score: Optional[int] = None
    components: Dict[str, Any]
    timestamp: datetime


class ActivityStats(BaseModel):
    """Activity statistics schema"""
    user_activity: Dict[str, Any]
    api_activity: Dict[str, Any]
    security_activity: Dict[str, Any]


class ComponentHealth(BaseModel):
    """Component health schema"""
    status: str
    response_time: Optional[float] = None
    error: Optional[str] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)


class PerformanceMetrics(BaseModel):
    """Performance metrics schema"""
    response_time_p95: float
    throughput: float
    error_rate: float
    availability: float


class Alert(BaseModel):
    """Alert schema"""
    id: str
    type: str
    message: str
    severity: str
    timestamp: datetime
