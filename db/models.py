"""Normalized database models for the sovereign AI security control plane."""

from __future__ import annotations

import enum
import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, Enum, Float, ForeignKey, Integer, JSON, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from core.database.database import Base


def new_id() -> str:
    return str(uuid.uuid4())


class UserRole(str, enum.Enum):
    ADMIN = "admin"
    USER = "user"
    SECURITY_ANALYST = "security_analyst"
    AI_OPERATOR = "ai_operator"


class UserStatus(str, enum.Enum):
    ACTIVE = "active"
    INACTIVE = "inactive"
    SUSPENDED = "suspended"
    LOCKED = "locked"


class SubscriptionTier(str, enum.Enum):
    FREE = "free"
    COMMUNITY = "community"
    GROWTH = "growth"
    SOVEREIGN = "sovereign"
    ENTERPRISE = "enterprise"
    FOUNDING = "founding"
    STANDARD = "standard"
    REGULATED = "regulated"


class ThreatType(str, enum.Enum):
    MALWARE = "malware"
    PHISHING = "phishing"
    BRUTE_FORCE = "brute_force"
    DATA_EXFILTRATION = "data_exfiltration"
    POLICY_VIOLATION = "policy_violation"
    ANOMALY = "anomaly"


class SecurityLevel(str, enum.Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class RuntimeMode(str, enum.Enum):
    BATCH = "batch"
    STANDBY = "standby"
    SCHEDULED = "scheduled"


class ActorVisibility(str, enum.Enum):
    PRIVATE = "private"
    PUBLIC = "public"
    UNLISTED = "unlisted"


class User(Base):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    username: Mapped[str] = mapped_column(String(80), unique=True, index=True)
    hashed_password: Mapped[str] = mapped_column(String(255))
    full_name: Mapped[str | None] = mapped_column(String(255))
    role: Mapped[UserRole] = mapped_column(Enum(UserRole), default=UserRole.USER, index=True)
    status: Mapped[UserStatus] = mapped_column(Enum(UserStatus), default=UserStatus.ACTIVE, index=True)
    mfa_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    failed_login_attempts: Mapped[int] = mapped_column(Integer, default=0)
    account_locked_until: Mapped[datetime | None] = mapped_column(DateTime)
    last_login: Mapped[datetime | None] = mapped_column(DateTime)
    last_activity: Mapped[datetime | None] = mapped_column(DateTime)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime | None] = mapped_column(DateTime, onupdate=datetime.utcnow)


class Workspace(Base):
    __tablename__ = "workspaces"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    owner_id: Mapped[str] = mapped_column(String(255), index=True)
    name: Mapped[str] = mapped_column(String(160))
    slug: Mapped[str] = mapped_column(String(180), unique=True, index=True)
    tier: Mapped[SubscriptionTier] = mapped_column(Enum(SubscriptionTier), default=SubscriptionTier.FREE)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    stripe_customer_id: Mapped[str | None] = mapped_column(String(255))
    stripe_subscription_id: Mapped[str | None] = mapped_column(String(255))
    subscription_status: Mapped[str] = mapped_column(String(50), default="inactive")
    seats_limit: Mapped[int] = mapped_column(Integer, default=5)
    ai_requests_limit: Mapped[int] = mapped_column(Integer, default=500)
    log_retention_days: Mapped[int] = mapped_column(Integer, default=7)
    settings: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime | None] = mapped_column(DateTime, onupdate=datetime.utcnow)


class UserSession(Base):
    __tablename__ = "user_sessions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    user_id: Mapped[str] = mapped_column(String(255), index=True)
    session_token: Mapped[str] = mapped_column(Text, unique=True)
    refresh_token: Mapped[str] = mapped_column(Text)
    ip_address: Mapped[str | None] = mapped_column(String(64))
    user_agent: Mapped[str | None] = mapped_column(String(512))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    expires_at: Mapped[datetime] = mapped_column(DateTime)
    last_accessed: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class WalletTransaction(Base):
    __tablename__ = "wallet_transactions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    workspace_id: Mapped[str] = mapped_column(String(36), index=True)
    amount_cents: Mapped[int] = mapped_column(Integer)
    balance_after_cents: Mapped[int] = mapped_column(Integer)
    event_type: Mapped[str] = mapped_column(String(80), index=True)
    description: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class AIProviderUsage(Base):
    __tablename__ = "ai_provider_usage"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    workspace_id: Mapped[str] = mapped_column(String(36), index=True)
    provider: Mapped[str] = mapped_column(String(80), index=True)
    model: Mapped[str] = mapped_column(String(120), index=True)
    route_type: Mapped[str] = mapped_column(String(40), default="byok", index=True)
    prompt_tokens: Mapped[int] = mapped_column(Integer, default=0)
    completion_tokens: Mapped[int] = mapped_column(Integer, default=0)
    request_count: Mapped[int] = mapped_column(Integer, default=1)
    provider_cost_cents: Mapped[int] = mapped_column(Integer, default=0)
    baseline_cost_cents: Mapped[int] = mapped_column(Integer, default=0)
    cache_hit: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    cache_savings_cents: Mapped[int] = mapped_column(Integer, default=0)
    local_route_savings_cents: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class ComplianceMapping(Base):
    __tablename__ = "compliance_mappings"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    framework: Mapped[str] = mapped_column(String(80), index=True)
    control_id: Mapped[str] = mapped_column(String(80), index=True)
    control_title: Mapped[str] = mapped_column(String(240))
    lockerphycer_configuration: Mapped[str] = mapped_column(Text)
    evidence_source: Mapped[str] = mapped_column(String(160))
    evidence_route: Mapped[str | None] = mapped_column(String(240))
    owner_role: Mapped[str] = mapped_column(String(80), default="security_admin")
    implementation_status: Mapped[str] = mapped_column(String(40), default="configured", index=True)
    export_notes: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class ManagedServiceQuote(Base):
    __tablename__ = "managed_service_quotes"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    workspace_id: Mapped[str | None] = mapped_column(String(36), index=True)
    environment_count: Mapped[int] = mapped_column(Integer, default=1)
    node_count: Mapped[int] = mapped_column(Integer, default=3)
    cluster_count: Mapped[int] = mapped_column(Integer, default=1)
    regulated_workload: Mapped[bool] = mapped_column(Boolean, default=False)
    air_gapped: Mapped[bool] = mapped_column(Boolean, default=False)
    monthly_fee_cents: Mapped[int] = mapped_column(Integer)
    onboarding_fee_cents: Mapped[int] = mapped_column(Integer)
    support_tier: Mapped[str] = mapped_column(String(80), default="managed")
    assumptions: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class AIModel(Base):
    __tablename__ = "ai_models"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    name: Mapped[str] = mapped_column(String(160))
    model_type: Mapped[str] = mapped_column(String(80), index=True)
    version: Mapped[str] = mapped_column(String(80))
    config: Mapped[dict] = mapped_column(JSON, default=dict)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    is_loaded: Mapped[bool] = mapped_column(Boolean, default=False)
    load_time: Mapped[float | None] = mapped_column(Float)
    performance_metrics: Mapped[dict | None] = mapped_column(JSON)
    last_trained: Mapped[datetime | None] = mapped_column(DateTime)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime | None] = mapped_column(DateTime, onupdate=datetime.utcnow)


class AIRequest(Base):
    __tablename__ = "ai_requests"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    user_id: Mapped[str] = mapped_column(String(255), index=True)
    model_id: Mapped[str] = mapped_column(String(36), index=True)
    workspace_id: Mapped[str | None] = mapped_column(String(36), index=True)
    request_type: Mapped[str] = mapped_column(String(80), index=True)
    input_data: Mapped[dict] = mapped_column(JSON, default=dict)
    output_data: Mapped[dict | None] = mapped_column(JSON)
    processing_time: Mapped[float | None] = mapped_column(Float)
    confidence_score: Mapped[float | None] = mapped_column(Float)
    tokens_used: Mapped[int | None] = mapped_column(Integer)
    cost: Mapped[float | None] = mapped_column(Float)
    status: Mapped[str] = mapped_column(String(40), default="queued", index=True)
    error_message: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime)


class SecurityEvent(Base):
    __tablename__ = "security_events"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    user_id: Mapped[str | None] = mapped_column(String(255), index=True)
    event_type: Mapped[str] = mapped_column(String(120), index=True)
    threat_type: Mapped[ThreatType | None] = mapped_column(Enum(ThreatType))
    security_level: Mapped[SecurityLevel] = mapped_column(Enum(SecurityLevel), default=SecurityLevel.MEDIUM, index=True)
    description: Mapped[str | None] = mapped_column(Text)
    details: Mapped[dict | None] = mapped_column(JSON)
    ip_address: Mapped[str | None] = mapped_column(String(64))
    user_agent: Mapped[str | None] = mapped_column(String(512))
    ai_confidence: Mapped[float | None] = mapped_column(Float)
    ai_analysis: Mapped[dict | None] = mapped_column(JSON)
    ai_recommendations: Mapped[dict | None] = mapped_column(JSON)
    status: Mapped[str] = mapped_column(String(40), default="open", index=True)
    assigned_to: Mapped[str | None] = mapped_column(String(255))
    resolution: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime | None] = mapped_column(DateTime, onupdate=datetime.utcnow)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime)


class SystemMetrics(Base):
    __tablename__ = "system_metrics"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    metric_name: Mapped[str] = mapped_column(String(120), index=True)
    metric_value: Mapped[float] = mapped_column(Float)
    labels: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class MarketplaceListing(Base):
    __tablename__ = "marketplace_listings"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    workspace_id: Mapped[str | None] = mapped_column(String(36), index=True)
    name: Mapped[str] = mapped_column(String(180))
    slug: Mapped[str] = mapped_column(String(200), unique=True, index=True)
    description: Mapped[str | None] = mapped_column(Text)
    category: Mapped[str] = mapped_column(String(80), default="tool", index=True)
    listing_type: Mapped[str] = mapped_column(String(80), default="tool", index=True)
    price_cents: Mapped[int] = mapped_column(Integer, default=0)
    downloads: Mapped[int] = mapped_column(Integer, default=0)
    rating: Mapped[float] = mapped_column(Float, default=0.0)
    metadata_: Mapped[dict] = mapped_column("metadata", JSON, default=dict)
    is_published: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime | None] = mapped_column(DateTime, onupdate=datetime.utcnow)


class Feedback(Base):
    __tablename__ = "feedback"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    user_id: Mapped[str | None] = mapped_column(String(255), index=True)
    category: Mapped[str] = mapped_column(String(80), index=True)
    subject: Mapped[str] = mapped_column(String(200))
    body: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(40), default="open", index=True)
    priority: Mapped[str] = mapped_column(String(40), default="normal")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime)


class GPCPlan(Base):
    __tablename__ = "gpc_plans"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    workspace_id: Mapped[str | None] = mapped_column(String(36), index=True)
    intent: Mapped[str] = mapped_column(Text)
    compiled_plan: Mapped[dict] = mapped_column(JSON, default=dict)
    risks: Mapped[list] = mapped_column(JSON, default=list)
    policy_requirements: Mapped[list] = mapped_column(JSON, default=list)
    cost_estimate: Mapped[dict] = mapped_column(JSON, default=dict)
    status: Mapped[str] = mapped_column(String(40), default="draft", index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime | None] = mapped_column(DateTime, onupdate=datetime.utcnow)


class AuditLog(Base):
    __tablename__ = "audit_logs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    user_id: Mapped[str | None] = mapped_column(String(255), index=True)
    action: Mapped[str] = mapped_column(String(120), index=True)
    resource_type: Mapped[str | None] = mapped_column(String(120), index=True)
    resource_id: Mapped[str | None] = mapped_column(String(120), index=True)
    details: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class UptimeCheck(Base):
    __tablename__ = "uptime_checks"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    service_name: Mapped[str] = mapped_column(String(80), index=True)
    status: Mapped[str] = mapped_column(String(40), default="up")
    response_time_ms: Mapped[int] = mapped_column(Integer, default=0)
    checked_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class Alert(Base):
    __tablename__ = "alerts"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    title: Mapped[str] = mapped_column(String(200))
    severity: Mapped[SecurityLevel] = mapped_column(Enum(SecurityLevel), default=SecurityLevel.MEDIUM)
    status: Mapped[str] = mapped_column(String(40), default="open")
    source: Mapped[str | None] = mapped_column(String(120))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class AgentDefinition(Base):
    __tablename__ = "agent_definitions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    agent_number: Mapped[int] = mapped_column(Integer, unique=True, index=True)
    name: Mapped[str] = mapped_column(String(160))
    codename: Mapped[str] = mapped_column(String(160))
    group: Mapped[str | None] = mapped_column(String(120))
    phase: Mapped[str | None] = mapped_column(String(120))
    committee: Mapped[str | None] = mapped_column(String(120))
    priority: Mapped[str | None] = mapped_column(String(40))
    mission: Mapped[str | None] = mapped_column(Text)
    capabilities: Mapped[list] = mapped_column(JSON, default=list)
    tools_allowed: Mapped[list] = mapped_column(JSON, default=list)
    tools_denied: Mapped[list] = mapped_column(JSON, default=list)
    guardrail_ids: Mapped[list] = mapped_column(JSON, default=list)
    voting_weight: Mapped[float] = mapped_column(Float, default=1.0)
    rank_level: Mapped[int] = mapped_column(Integer, default=50)
    status: Mapped[str] = mapped_column(String(40), default="standby", index=True)
    is_control_agent: Mapped[bool] = mapped_column(Boolean, default=False)
    config: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class AgentRun(Base):
    __tablename__ = "agent_runs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    agent_id: Mapped[str | None] = mapped_column(String(36), index=True)
    agent_number: Mapped[int | None] = mapped_column(Integer, index=True)
    agent_name: Mapped[str | None] = mapped_column(String(160))
    group: Mapped[str | None] = mapped_column(String(120))
    task: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(40), default="queued", index=True)
    cost_cents: Mapped[int] = mapped_column(Integer, default=0)
    tokens_used: Mapped[int] = mapped_column(Integer, default=0)
    errors: Mapped[list] = mapped_column(JSON, default=list)
    blocked_mutations: Mapped[list] = mapped_column(JSON, default=list)
    approval_required: Mapped[bool] = mapped_column(Boolean, default=False)
    evidence_id: Mapped[str | None] = mapped_column(String(36))
    audit_hash: Mapped[str | None] = mapped_column(String(128))
    started_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime)


class DecisionFrame(Base):
    __tablename__ = "decision_frames"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    agent_id: Mapped[str | None] = mapped_column(String(36), index=True)
    actor: Mapped[str | None] = mapped_column(String(160))
    objective: Mapped[str] = mapped_column(Text)
    risk_tier: Mapped[str] = mapped_column(String(40), default="low")
    proof_hash: Mapped[str | None] = mapped_column(String(128))
    replay_status: Mapped[str] = mapped_column(String(40), default="pending")
    cost_estimate_cents: Mapped[int] = mapped_column(Integer, default=0)
    tools_allowed: Mapped[list] = mapped_column(JSON, default=list)
    tools_denied: Mapped[list] = mapped_column(JSON, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class AgentSignal(Base):
    __tablename__ = "agent_signals"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    agent_id: Mapped[str | None] = mapped_column(String(36), index=True)
    signal_type: Mapped[str] = mapped_column(String(80), index=True)
    severity: Mapped[str] = mapped_column(String(40), default="info")
    source: Mapped[str | None] = mapped_column(String(120))
    summary: Mapped[str | None] = mapped_column(Text)
    score: Mapped[float] = mapped_column(Float, default=0.0)
    status: Mapped[str] = mapped_column(String(40), default="open")
    routed_to: Mapped[str | None] = mapped_column(String(120))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class AgentViolation(Base):
    __tablename__ = "agent_violations"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    agent_id: Mapped[str | None] = mapped_column(String(36), index=True)
    agent_number: Mapped[int | None] = mapped_column(Integer, index=True)
    guardrail_id: Mapped[str | None] = mapped_column(String(80))
    guardrail_name: Mapped[str | None] = mapped_column(String(160))
    severity: Mapped[str] = mapped_column(String(40))
    description: Mapped[str | None] = mapped_column(Text)
    penalty_points: Mapped[int] = mapped_column(Integer, default=0)
    resolved: Mapped[bool] = mapped_column(Boolean, default=False)
    resolution: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime)


class AgentReward(Base):
    __tablename__ = "agent_rewards"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    agent_id: Mapped[str | None] = mapped_column(String(36), index=True)
    agent_number: Mapped[int | None] = mapped_column(Integer, index=True)
    reward_type: Mapped[str] = mapped_column(String(80))
    description: Mapped[str | None] = mapped_column(Text)
    points: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class AgentCouncilVote(Base):
    __tablename__ = "agent_council_votes"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    agent_id: Mapped[str | None] = mapped_column(String(36), index=True)
    agent_number: Mapped[int | None] = mapped_column(Integer, index=True)
    proposal_id: Mapped[str] = mapped_column(String(120), index=True)
    proposal_summary: Mapped[str | None] = mapped_column(Text)
    vote: Mapped[str] = mapped_column(String(40))
    voting_weight: Mapped[float] = mapped_column(Float, default=1.0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class IntelFreezeReport(Base):
    __tablename__ = "intel_freeze_reports"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    initiated_by: Mapped[str | None] = mapped_column(String(160))
    snapshot_id: Mapped[str | None] = mapped_column(String(120))
    reason: Mapped[str | None] = mapped_column(Text)
    blocked_mutations: Mapped[list] = mapped_column(JSON, default=list)
    blocked_agents: Mapped[list] = mapped_column(JSON, default=list)
    status: Mapped[str] = mapped_column(String(40), default="frozen")
    frozen_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    unfrozen_at: Mapped[datetime | None] = mapped_column(DateTime)


class EvidenceArtifact(Base):
    __tablename__ = "evidence_artifacts"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    agent_id: Mapped[str | None] = mapped_column(String(36), index=True)
    artifact_type: Mapped[str] = mapped_column(String(80), index=True)
    title: Mapped[str] = mapped_column(String(200))
    description: Mapped[str | None] = mapped_column(Text)
    content_hash: Mapped[str] = mapped_column(String(128), index=True)
    storage_path: Mapped[str | None] = mapped_column(String(512))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class ActorDefinition(Base):
    __tablename__ = "actor_definitions"
    __table_args__ = (UniqueConstraint("actor_id", name="uq_actor_id"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    actor_id: Mapped[str] = mapped_column(String(160), index=True)
    name: Mapped[str] = mapped_column(String(180))
    description: Mapped[str | None] = mapped_column(Text)
    version: Mapped[str] = mapped_column(String(40), default="1.0.0")
    pack_type: Mapped[str] = mapped_column(String(80), default="execution_pack")
    category: Mapped[str | None] = mapped_column(String(80), index=True)
    industry: Mapped[str | None] = mapped_column(String(80), index=True)
    runtime_mode: Mapped[RuntimeMode] = mapped_column(Enum(RuntimeMode), default=RuntimeMode.BATCH)
    runtime: Mapped[str] = mapped_column(String(80), default="docker")
    entrypoint: Mapped[str | None] = mapped_column(String(255))
    input_schema: Mapped[dict] = mapped_column(JSON, default=dict)
    output_schema: Mapped[dict] = mapped_column(JSON, default=dict)
    policy_pack: Mapped[str | None] = mapped_column(String(120))
    risk_tier: Mapped[str] = mapped_column(String(40), default="low")
    evidence_required: Mapped[bool] = mapped_column(Boolean, default=False)
    requires_human_review: Mapped[bool] = mapped_column(Boolean, default=False)
    allowed_models: Mapped[list] = mapped_column(JSON, default=list)
    allowed_tools: Mapped[list] = mapped_column(JSON, default=list)
    denied_tools: Mapped[list] = mapped_column(JSON, default=list)
    cost_ceiling_cents: Mapped[int] = mapped_column(Integer, default=100)
    standby_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    standby_idle_timeout_seconds: Mapped[int] = mapped_column(Integer, default=300)
    standby_max_requests: Mapped[int] = mapped_column(Integer, default=20)
    standby_memory_mb: Mapped[int] = mapped_column(Integer, default=512)
    standby_readiness_path: Mapped[str] = mapped_column(String(160), default="/health")
    visibility: Mapped[ActorVisibility] = mapped_column(Enum(ActorVisibility), default=ActorVisibility.PRIVATE)
    tenant_scoped: Mapped[bool] = mapped_column(Boolean, default=True)
    marketplace_installable: Mapped[bool] = mapped_column(Boolean, default=False)
    status: Mapped[str] = mapped_column(String(40), default="active")
    config: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class ActorRun(Base):
    __tablename__ = "actor_runs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    actor_def_id: Mapped[str | None] = mapped_column(String(36), index=True)
    actor_id: Mapped[str] = mapped_column(String(160), index=True)
    runtime_mode: Mapped[RuntimeMode] = mapped_column(Enum(RuntimeMode), default=RuntimeMode.BATCH)
    workspace_id: Mapped[str | None] = mapped_column(String(36), index=True)
    tenant_id: Mapped[str | None] = mapped_column(String(120), index=True)
    user_id: Mapped[str | None] = mapped_column(String(255), index=True)
    agent_id: Mapped[str | None] = mapped_column(String(36), index=True)
    input_hash: Mapped[str | None] = mapped_column(String(64))
    output_hash: Mapped[str | None] = mapped_column(String(64))
    input_data: Mapped[dict | None] = mapped_column(JSON)
    output_data: Mapped[dict | None] = mapped_column(JSON)
    policy_result: Mapped[str | None] = mapped_column(String(80))
    risk_tier: Mapped[str] = mapped_column(String(40), default="low")
    model_provider: Mapped[str | None] = mapped_column(String(80))
    tools_used: Mapped[list] = mapped_column(JSON, default=list)
    cost_estimate_cents: Mapped[int] = mapped_column(Integer, default=0)
    latency_ms: Mapped[int | None] = mapped_column(Integer)
    tokens_used: Mapped[int] = mapped_column(Integer, default=0)
    evidence_id: Mapped[str | None] = mapped_column(String(36))
    proof_hash: Mapped[str | None] = mapped_column(String(128))
    audit_hash: Mapped[str | None] = mapped_column(String(128))
    status: Mapped[str] = mapped_column(String(40), default="queued", index=True)
    error_message: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    started_at: Mapped[datetime | None] = mapped_column(DateTime)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime)
