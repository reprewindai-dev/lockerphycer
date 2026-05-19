"""
Database Models for Locker Phycer
"""

from sqlalchemy import Column, Integer, String, DateTime, Boolean, Text, JSON, ForeignKey, Enum, Float
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from datetime import datetime
from enum import Enum as PyEnum
import uuid

from core.database.database import Base


class UserRole(PyEnum):
    """User roles"""
    ADMIN = "admin"
    USER = "user"
    SECURITY_ANALYST = "security_analyst"
    AI_OPERATOR = "ai_operator"


class UserStatus(PyEnum):
    """User status"""
    ACTIVE = "active"
    INACTIVE = "inactive"
    SUSPENDED = "suspended"
    LOCKED = "locked"


class SecurityLevel(PyEnum):
    """Security levels"""
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class ThreatType(PyEnum):
    """Threat types"""
    MALWARE = "malware"
    PHISHING = "phishing"
    DDOS = "ddos"
    INTRUSION = "intrusion"
    DATA_BREACH = "data_breach"
    ANOMALY = "anomaly"


class User(Base):
    """User model"""
    __tablename__ = "users"
    
    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    email = Column(String, unique=True, index=True, nullable=False)
    username = Column(String, unique=True, index=True, nullable=False)
    hashed_password = Column(String, nullable=False)
    full_name = Column(String)
    role = Column(Enum(UserRole), default=UserRole.USER)
    status = Column(Enum(UserStatus), default=UserStatus.ACTIVE)
    
    # Security settings
    mfa_enabled = Column(Boolean, default=False)
    mfa_secret = Column(String)
    failed_login_attempts = Column(Integer, default=0)
    last_login = Column(DateTime(timezone=True))
    account_locked_until = Column(DateTime(timezone=True))
    
    # Metadata
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())
    last_activity = Column(DateTime(timezone=True))
    
    # Relationships
    sessions = relationship("UserSession", back_populates="user", cascade="all, delete-orphan")
    security_events = relationship("SecurityEvent", back_populates="user", foreign_keys="[SecurityEvent.user_id]")
    ai_requests = relationship("AIRequest", back_populates="user")


class UserSession(Base):
    """User session model"""
    __tablename__ = "user_sessions"
    
    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id = Column(String, ForeignKey("users.id"), nullable=False)
    session_token = Column(String, unique=True, index=True, nullable=False)
    refresh_token = Column(String, unique=True, index=True)
    
    # Session metadata
    ip_address = Column(String)
    user_agent = Column(Text)
    device_fingerprint = Column(String)
    location = Column(JSON)
    
    # Timestamps
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    expires_at = Column(DateTime(timezone=True), nullable=False)
    last_accessed = Column(DateTime(timezone=True), server_default=func.now())
    is_active = Column(Boolean, default=True)
    
    # Relationships
    user = relationship("User", back_populates="sessions")


class SecurityEvent(Base):
    """Security event model"""
    __tablename__ = "security_events"
    
    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id = Column(String, ForeignKey("users.id"))
    
    # Event details
    event_type = Column(String, nullable=False, index=True)
    threat_type = Column(Enum(ThreatType))
    security_level = Column(Enum(SecurityLevel), default=SecurityLevel.MEDIUM)
    
    # Event data
    description = Column(Text)
    details = Column(JSON)
    ip_address = Column(String)
    user_agent = Column(Text)
    
    # AI analysis
    ai_confidence = Column(Float)
    ai_analysis = Column(JSON)
    ai_recommendations = Column(JSON)
    
    # Status
    status = Column(String, default="open")  # open, investigating, resolved, false_positive
    assigned_to = Column(String, ForeignKey("users.id"))
    
    # Timestamps
    created_at = Column(DateTime(timezone=True), server_default=func.now(), index=True)
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())
    resolved_at = Column(DateTime(timezone=True))
    
    # Relationships
    user = relationship("User", back_populates="security_events", foreign_keys=[user_id])
    assignee = relationship("User", foreign_keys=[assigned_to])


class AIModel(Base):
    """AI Model configuration"""
    __tablename__ = "ai_models"
    
    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    name = Column(String, unique=True, nullable=False)
    model_type = Column(String, nullable=False)  # classification, detection, analysis
    version = Column(String, nullable=False)
    
    # Model configuration
    config = Column(JSON)
    parameters = Column(JSON)
    performance_metrics = Column(JSON)
    
    # Status
    is_active = Column(Boolean, default=True)
    is_loaded = Column(Boolean, default=False)
    load_time = Column(Float)
    
    # Timestamps
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())
    last_trained = Column(DateTime(timezone=True))
    
    # Relationships
    requests = relationship("AIRequest", back_populates="model")


class AIRequest(Base):
    """AI Request tracking"""
    __tablename__ = "ai_requests"
    
    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id = Column(String, ForeignKey("users.id"))
    model_id = Column(String, ForeignKey("ai_models.id"))
    
    # Request details
    request_type = Column(String, nullable=False)
    input_data = Column(JSON)
    output_data = Column(JSON)
    
    # Performance metrics
    processing_time = Column(Float)
    confidence_score = Column(Float)
    tokens_used = Column(Integer)
    cost = Column(Float)
    
    # Status
    status = Column(String, default="pending")  # pending, processing, completed, failed
    error_message = Column(Text)
    
    # Timestamps
    created_at = Column(DateTime(timezone=True), server_default=func.now(), index=True)
    completed_at = Column(DateTime(timezone=True))
    
    # Relationships
    user = relationship("User", back_populates="ai_requests")
    model = relationship("AIModel", back_populates="requests")


class SystemMetrics(Base):
    """System performance metrics"""
    __tablename__ = "system_metrics"
    
    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    
    # Metric details
    metric_name = Column(String, nullable=False, index=True)
    metric_value = Column(Float, nullable=False)
    metric_unit = Column(String)
    
    # Dimensions
    service = Column(String, index=True)
    environment = Column(String)
    region = Column(String)
    
    # Timestamps
    timestamp = Column(DateTime(timezone=True), server_default=func.now(), index=True)
    
    # Additional metadata
    tags = Column(JSON)
    extra_metadata = Column("metadata", JSON)


class AuditLog(Base):
    """Audit log for compliance"""
    __tablename__ = "audit_logs"
    
    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id = Column(String, ForeignKey("users.id"))
    
    # Action details
    action = Column(String, nullable=False)
    resource_type = Column(String)
    resource_id = Column(String)
    
    # Change details
    old_values = Column(JSON)
    new_values = Column(JSON)
    
    # Request context
    ip_address = Column(String)
    user_agent = Column(Text)
    session_id = Column(String)
    
    # Timestamps
    created_at = Column(DateTime(timezone=True), server_default=func.now(), index=True)
    
    # Relationships
    user = relationship("User")


class Alert(Base):
    """System alerts"""
    __tablename__ = "alerts"
    
    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    
    # Alert details
    title = Column(String, nullable=False)
    description = Column(Text)
    severity = Column(Enum(SecurityLevel), default=SecurityLevel.MEDIUM)
    alert_type = Column(String, nullable=False, index=True)
    
    # Status
    status = Column(String, default="open")  # open, acknowledged, resolved
    assigned_to = Column(String, ForeignKey("users.id"))
    
    # Metadata
    source = Column(String)
    details = Column(JSON)
    resolution = Column(Text)
    
    # Timestamps
    created_at = Column(DateTime(timezone=True), server_default=func.now(), index=True)
    acknowledged_at = Column(DateTime(timezone=True))
    resolved_at = Column(DateTime(timezone=True))
    
    # Relationships
    assignee = relationship("User")


class Configuration(Base):
    """System configuration"""
    __tablename__ = "configurations"
    
    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    
    # Configuration details
    key = Column(String, unique=True, nullable=False, index=True)
    value = Column(JSON)
    description = Column(Text)
    
    # Metadata
    category = Column(String, index=True)
    is_sensitive = Column(Boolean, default=False)
    is_readonly = Column(Boolean, default=False)
    
    # Timestamps
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())
    updated_by = Column(String, ForeignKey("users.id"))
    
    # Relationships
    updater = relationship("User")


# ---------------------------------------------------------------------------
# Veklom Sovereign AI Hub models
# ---------------------------------------------------------------------------

class SubscriptionTier(PyEnum):
    FREE = "free"
    FOUNDING = "founding"
    STANDARD = "standard"
    REGULATED = "regulated"


class Workspace(Base):
    """Tenant workspace"""
    __tablename__ = "workspaces"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    owner_id = Column(String, ForeignKey("users.id"), nullable=False)
    name = Column(String, nullable=False)
    slug = Column(String, unique=True, index=True)
    tier = Column(Enum(SubscriptionTier), default=SubscriptionTier.FREE)
    is_active = Column(Boolean, default=True)
    settings = Column(JSON, default=dict)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    owner = relationship("User")
    listings = relationship("MarketplaceListing", back_populates="workspace")


class MarketplaceListing(Base):
    """Marketplace tool/model listing"""
    __tablename__ = "marketplace_listings"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    workspace_id = Column(String, ForeignKey("workspaces.id"))
    vendor_id = Column(String, ForeignKey("users.id"))
    name = Column(String, nullable=False)
    slug = Column(String, index=True)
    description = Column(Text)
    category = Column(String, index=True)
    listing_type = Column(String, default="tool")
    price_cents = Column(Integer, default=0)
    is_published = Column(Boolean, default=False)
    downloads = Column(Integer, default=0)
    rating = Column(Float, default=0.0)
    metadata_ = Column("metadata", JSON, default=dict)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    workspace = relationship("Workspace", back_populates="listings")
    vendor = relationship("User")


class WalletTransaction(Base):
    """Operating reserve / wallet transaction"""
    __tablename__ = "wallet_transactions"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    workspace_id = Column(String, ForeignKey("workspaces.id"), nullable=False)
    amount_cents = Column(Integer, nullable=False)
    balance_after_cents = Column(Integer, nullable=False)
    event_type = Column(String, nullable=False)
    description = Column(Text)
    created_at = Column(DateTime(timezone=True), server_default=func.now())


class Feedback(Base):
    """User feedback / bug reports / suggestions"""
    __tablename__ = "feedback"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id = Column(String, ForeignKey("users.id"))
    category = Column(String, nullable=False, default="general")
    subject = Column(String, nullable=False)
    body = Column(Text, nullable=False)
    status = Column(String, default="open")
    priority = Column(String, default="normal")
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    resolved_at = Column(DateTime(timezone=True))

    user = relationship("User")


class UptimeCheck(Base):
    """Uptime monitoring records"""
    __tablename__ = "uptime_checks"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    service_name = Column(String, nullable=False, index=True)
    status = Column(String, nullable=False, default="up")
    response_time_ms = Column(Float)
    status_code = Column(Integer)
    details = Column(JSON)
    checked_at = Column(DateTime(timezone=True), server_default=func.now(), index=True)


class GPCPlan(Base):
    """GPC — Governed Plan Compiler outputs"""
    __tablename__ = "gpc_plans"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    workspace_id = Column(String, ForeignKey("workspaces.id"))
    user_id = Column(String, ForeignKey("users.id"))
    intent = Column(Text, nullable=False)
    compiled_plan = Column(JSON)
    risks = Column(JSON)
    policy_requirements = Column(JSON)
    cost_estimate = Column(JSON)
    status = Column(String, default="draft")
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    user = relationship("User")
