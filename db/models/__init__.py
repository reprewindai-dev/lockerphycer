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


# ---------------------------------------------------------------------------
# Agent Workforce models
# ---------------------------------------------------------------------------

class AgentCapability(PyEnum):
    """Special agent capabilities — the X-Men model"""
    EYES = "eyes"
    ARMS = "arms"
    LEGS = "legs"
    ZENO = "zeno"
    GLADIATOR = "gladiator"
    HRM = "hrm"
    RAG = "rag"
    LISTENER = "listener"
    SCIENTIST = "scientist"
    SENTINEL = "sentinel"


class AgentStatus(PyEnum):
    """Agent operational status"""
    ACTIVE = "active"
    STANDBY = "standby"
    FROZEN = "frozen"
    DECOMMISSIONED = "decommissioned"
    PENALTY = "penalty"


class AgentDefinition(Base):
    """Registry entry for every agent in the workforce"""
    __tablename__ = "agent_definitions"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    agent_number = Column(Integer, unique=True, nullable=False, index=True)
    name = Column(String, nullable=False, index=True)
    codename = Column(String, unique=True, nullable=False, index=True)
    group = Column(String, nullable=False, index=True)
    phase = Column(String, nullable=False)
    committee = Column(String, nullable=False, index=True)
    priority = Column(String, default="MEDIUM")
    mission = Column(Text, nullable=False)
    capabilities = Column(JSON, default=list)
    tools_allowed = Column(JSON, default=list)
    tools_denied = Column(JSON, default=list)
    guardrail_ids = Column(JSON, default=list)
    voting_weight = Column(Float, default=1.0)
    rank_level = Column(Integer, default=50)
    status = Column(
        Enum(AgentStatus), default=AgentStatus.STANDBY, index=True
    )
    is_control_agent = Column(Boolean, default=False)
    config = Column(JSON, default=dict)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    runs = relationship("AgentRun", back_populates="agent")


class AgentRun(Base):
    """Immutable record of a single agent execution"""
    __tablename__ = "agent_runs"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    agent_id = Column(
        String, ForeignKey("agent_definitions.id"), nullable=False, index=True
    )
    agent_number = Column(Integer, nullable=False, index=True)
    agent_name = Column(String, nullable=False)
    group = Column(String, nullable=False)
    task = Column(Text, nullable=False)
    status = Column(String, default="pending", index=True)
    tool_calls = Column(JSON, default=list)
    cost_cents = Column(Integer, default=0)
    tokens_used = Column(Integer, default=0)
    errors = Column(JSON, default=list)
    blocked_mutations = Column(JSON, default=list)
    approval_required = Column(Boolean, default=False)
    evidence_id = Column(String)
    audit_hash = Column(String)
    started_at = Column(DateTime(timezone=True), server_default=func.now())
    ended_at = Column(DateTime(timezone=True))

    agent = relationship("AgentDefinition", back_populates="runs")


class DecisionFrame(Base):
    """SHA-256 sealed, immutable record of agent decisions"""
    __tablename__ = "decision_frames"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    agent_id = Column(
        String, ForeignKey("agent_definitions.id"), nullable=False, index=True
    )
    agent_run_id = Column(
        String, ForeignKey("agent_runs.id"), index=True
    )
    workspace_id = Column(String, ForeignKey("workspaces.id"))
    actor = Column(String, nullable=False)
    objective = Column(Text, nullable=False)
    policy_pack = Column(JSON, default=dict)
    risk_tier = Column(String, default="low")
    tools_allowed = Column(JSON, default=list)
    tools_denied = Column(JSON, default=list)
    cost_estimate_cents = Column(Integer, default=0)
    evidence_requirements = Column(JSON, default=list)
    final_action = Column(Text)
    proof_hash = Column(String)
    replay_status = Column(String, default="pending")
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    agent = relationship("AgentDefinition")
    run = relationship("AgentRun")


class AgentSignal(Base):
    """Signals captured by listener/monitoring agents"""
    __tablename__ = "agent_signals"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    agent_id = Column(
        String, ForeignKey("agent_definitions.id"), nullable=False, index=True
    )
    signal_type = Column(String, nullable=False, index=True)
    severity = Column(String, default="info")
    source = Column(String, nullable=False)
    summary = Column(Text, nullable=False)
    details = Column(JSON, default=dict)
    score = Column(Float, default=0.0)
    routed_to = Column(String)
    status = Column(String, default="open", index=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), index=True)

    agent = relationship("AgentDefinition")


class AgentViolation(Base):
    """Guardrail violation records"""
    __tablename__ = "agent_violations"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    agent_id = Column(
        String, ForeignKey("agent_definitions.id"), nullable=False, index=True
    )
    agent_run_id = Column(String, ForeignKey("agent_runs.id"))
    guardrail_id = Column(String, nullable=False, index=True)
    guardrail_name = Column(String, nullable=False)
    severity = Column(String, nullable=False)
    description = Column(Text, nullable=False)
    evidence = Column(JSON, default=dict)
    penalty_applied = Column(String)
    penalty_points = Column(Integer, default=0)
    resolved = Column(Boolean, default=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), index=True)

    agent = relationship("AgentDefinition")
    run = relationship("AgentRun")


class AgentReward(Base):
    """Incentive and reward records"""
    __tablename__ = "agent_rewards"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    agent_id = Column(
        String, ForeignKey("agent_definitions.id"), nullable=False, index=True
    )
    reward_type = Column(String, nullable=False)
    description = Column(Text, nullable=False)
    points = Column(Integer, default=0)
    rank_change = Column(String)
    voting_weight_change = Column(Float, default=0.0)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    agent = relationship("AgentDefinition")


class AgentCouncilVote(Base):
    """Sovereign council voting records"""
    __tablename__ = "agent_council_votes"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    agent_id = Column(
        String, ForeignKey("agent_definitions.id"), nullable=False, index=True
    )
    proposal_id = Column(String, nullable=False, index=True)
    proposal_summary = Column(Text, nullable=False)
    vote = Column(String, nullable=False)
    voting_weight = Column(Float, default=1.0)
    reasoning = Column(Text)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    agent = relationship("AgentDefinition")


class IntelFreezeReport(Base):
    """Records of FREEZE_INTEL activations"""
    __tablename__ = "intel_freeze_reports"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    initiated_by = Column(String, nullable=False)
    snapshot_id = Column(String, nullable=False)
    reason = Column(Text, nullable=False)
    blocked_mutations = Column(JSON, default=list)
    blocked_agents = Column(JSON, default=list)
    status = Column(String, default="active", index=True)
    confirmed_unfreeze_by = Column(String)
    frozen_at = Column(DateTime(timezone=True), server_default=func.now())
    unfrozen_at = Column(DateTime(timezone=True))


class EvidenceArtifact(Base):
    """Immutable evidence artifacts for audit trail"""
    __tablename__ = "evidence_artifacts"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    agent_id = Column(String, ForeignKey("agent_definitions.id"), index=True)
    agent_run_id = Column(String, ForeignKey("agent_runs.id"))
    artifact_type = Column(String, nullable=False, index=True)
    title = Column(String, nullable=False)
    description = Column(Text)
    content_hash = Column(String, nullable=False)
    storage_path = Column(String)
    metadata_ = Column("metadata", JSON, default=dict)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), index=True)

    agent = relationship("AgentDefinition")
    run = relationship("AgentRun")


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


# ---------------------------------------------------------------------------
# Execution Packs / Actor models (Apify-inspired, Veklom-native)
# ---------------------------------------------------------------------------

class RuntimeMode(PyEnum):
    BATCH = "batch"
    STANDBY = "standby"
    SCHEDULED = "scheduled"


class ActorVisibility(PyEnum):
    PRIVATE = "private"
    PUBLIC = "public"
    UNLISTED = "unlisted"


class ActorDefinition(Base):
    """Veklom Execution Pack / Actor definition"""
    __tablename__ = "actor_definitions"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    actor_id = Column(String, unique=True, nullable=False, index=True)
    name = Column(String, nullable=False)
    description = Column(Text)
    version = Column(String, nullable=False, default="1.0.0")

    # Type and classification
    pack_type = Column(String, nullable=False, default="execution_pack")
    category = Column(String, index=True)
    industry = Column(String, index=True)

    # Runtime
    runtime_mode = Column(Enum(RuntimeMode), default=RuntimeMode.BATCH)
    runtime = Column(String, default="docker")
    entrypoint = Column(String)

    # Schemas
    input_schema = Column(JSON, default=dict)
    output_schema = Column(JSON, default=dict)

    # Policy and governance
    policy_pack = Column(String)
    risk_tier = Column(String, default="low")
    evidence_required = Column(Boolean, default=False)
    requires_human_review = Column(Boolean, default=False)
    allowed_models = Column(JSON, default=list)
    allowed_tools = Column(JSON, default=list)
    denied_tools = Column(JSON, default=list)
    cost_ceiling_cents = Column(Integer, default=100)

    # Standby configuration
    standby_enabled = Column(Boolean, default=False)
    standby_port_env = Column(String, default="VEKLOM_STANDBY_PORT")
    standby_readiness_path = Column(String, default="/")
    standby_idle_timeout_seconds = Column(Integer, default=300)
    standby_max_requests = Column(Integer, default=20)
    standby_desired_requests = Column(Integer, default=10)
    standby_memory_mb = Column(Integer, default=512)

    # Tenant and visibility
    visibility = Column(Enum(ActorVisibility), default=ActorVisibility.PRIVATE)
    tenant_scoped = Column(Boolean, default=True)
    workspace_id = Column(String, index=True)

    # Marketplace
    marketplace_installable = Column(Boolean, default=False)
    marketplace_listing_id = Column(String)

    # Creator tracking
    created_by_agent_id = Column(String)
    created_by_user_id = Column(String)

    # Config blob
    config = Column(JSON, default=dict)

    # Status
    status = Column(String, default="draft")
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    runs = relationship("ActorRun", back_populates="actor")


class ActorRun(Base):
    """Individual execution of an Actor / Execution Pack"""
    __tablename__ = "actor_runs"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    actor_def_id = Column(String, ForeignKey("actor_definitions.id"), index=True)
    actor_id = Column(String, nullable=False, index=True)

    # Runtime context
    runtime_mode = Column(Enum(RuntimeMode), default=RuntimeMode.BATCH)
    workspace_id = Column(String, index=True)
    tenant_id = Column(String, index=True)
    user_id = Column(String)
    agent_id = Column(String)

    # Input/Output
    input_hash = Column(String)
    output_hash = Column(String)
    input_data = Column(JSON)
    output_data = Column(JSON)

    # Policy and governance
    policy_result = Column(String)
    risk_tier = Column(String)
    model_provider = Column(String)
    tools_used = Column(JSON, default=list)

    # Metrics
    cost_estimate_cents = Column(Integer, default=0)
    latency_ms = Column(Integer)
    tokens_used = Column(Integer, default=0)

    # Evidence and proof
    evidence_id = Column(String)
    proof_hash = Column(String)
    audit_hash = Column(String)

    # Status
    status = Column(String, default="pending", index=True)
    error_message = Column(Text)

    # Timestamps
    created_at = Column(DateTime(timezone=True), server_default=func.now(), index=True)
    started_at = Column(DateTime(timezone=True))
    ended_at = Column(DateTime(timezone=True))

    actor = relationship("ActorDefinition", back_populates="runs")
