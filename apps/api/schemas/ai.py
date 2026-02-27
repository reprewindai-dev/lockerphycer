"""
AI Services Schemas
"""

from pydantic import BaseModel, Field
from typing import Dict, Any, Optional
from datetime import datetime


class AIModelBase(BaseModel):
    """Base AI model schema"""
    name: str
    model_type: str
    version: str
    config: Optional[Dict[str, Any]] = None


class AIModelResponse(AIModelBase):
    """AI model response schema"""
    id: str
    is_active: bool
    is_loaded: bool
    load_time: Optional[float] = None
    performance_metrics: Optional[Dict[str, Any]] = None
    created_at: datetime
    updated_at: Optional[datetime] = None
    last_trained: Optional[datetime] = None
    
    class Config:
        from_attributes = True


class AIRequestBase(BaseModel):
    """Base AI request schema"""
    request_type: str
    input_data: Dict[str, Any]


class AIAnalysisRequest(AIRequestBase):
    """AI analysis request schema"""
    model_id: str


class AIAnalysisResponse(BaseModel):
    """AI analysis response schema"""
    request_id: str
    model_id: str
    model_name: str
    analysis: Dict[str, Any]
    confidence: float
    processing_time: float
    timestamp: datetime


class AIRequestResponse(BaseModel):
    """AI request response schema"""
    id: str
    user_id: str
    model_id: str
    request_type: str
    input_data: Dict[str, Any]
    output_data: Optional[Dict[str, Any]] = None
    processing_time: Optional[float] = None
    confidence_score: Optional[float] = None
    tokens_used: Optional[int] = None
    cost: Optional[float] = None
    status: str
    error_message: Optional[str] = None
    created_at: datetime
    completed_at: Optional[datetime] = None
    
    class Config:
        from_attributes = True


class AIStats(BaseModel):
    """AI statistics schema"""
    total_requests_today: int
    successful_requests_today: int
    success_rate: float
    active_models: int
    avg_processing_time: float


class ModelUpload(BaseModel):
    """Model upload schema"""
    name: str
    model_type: str
    version: str
    description: Optional[str] = None
