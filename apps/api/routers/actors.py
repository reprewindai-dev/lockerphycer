"""Veklom Execution Packs / Actor router.

Apify-inspired, Veklom-native governed runtime for installable
runnable packages with batch, standby, and scheduled modes.

Terminology:
  Agent = internal Veklom workforce unit (not for sale)
  Actor = developer/runtime name for executable unit
  Execution Pack = customer/marketplace-facing installable package
"""

import hashlib
import logging
from datetime import datetime, timedelta
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import select, func, desc
from sqlalchemy.ext.asyncio import AsyncSession

from core.config.settings import settings
from core.database.database import get_db
from core.security.auth import require_admin
from db.models import ActorDefinition, ActorRun, RuntimeMode, ActorVisibility

router = APIRouter(prefix="/actors", tags=["Execution Packs"])
logger = logging.getLogger(__name__)

ADMIN_EMAIL = settings.ADMIN_EMAIL


# ---------------------------------------------------------------------------
# Pydantic schemas
# ---------------------------------------------------------------------------

class ActorCreateRequest(BaseModel):
    actor_id: str
    name: str
    description: Optional[str] = None
    version: str = "1.0.0"
    pack_type: str = "execution_pack"
    category: Optional[str] = None
    industry: Optional[str] = None
    runtime_mode: str = "batch"
    runtime: str = "docker"
    entrypoint: Optional[str] = None
    input_schema: dict = Field(default_factory=dict)
    output_schema: dict = Field(default_factory=dict)
    policy_pack: Optional[str] = None
    risk_tier: str = "low"
    evidence_required: bool = False
    requires_human_review: bool = False
    allowed_models: list = Field(default_factory=list)
    allowed_tools: list = Field(default_factory=list)
    denied_tools: list = Field(default_factory=list)
    cost_ceiling_cents: int = 100
    standby_enabled: bool = False
    standby_idle_timeout_seconds: int = 300
    standby_max_requests: int = 20
    standby_memory_mb: int = 512
    visibility: str = "private"
    tenant_scoped: bool = True
    marketplace_installable: bool = False


class ActorRunRequest(BaseModel):
    workspace_id: Optional[str] = None
    tenant_id: Optional[str] = None
    user_id: Optional[str] = None
    agent_id: Optional[str] = None
    input_data: Optional[dict] = None
    risk_tier: Optional[str] = None
    model_provider: Optional[str] = None


class ActorRunCompleteRequest(BaseModel):
    status: str = "completed"
    output_data: Optional[dict] = None
    policy_result: Optional[str] = None
    tools_used: list = Field(default_factory=list)
    cost_estimate_cents: int = 0
    tokens_used: int = 0
    latency_ms: Optional[int] = None
    error_message: Optional[str] = None


# ---------------------------------------------------------------------------
# CRUD — Actor definitions
# ---------------------------------------------------------------------------

@router.get("")
async def list_actors(
    category: Optional[str] = None,
    industry: Optional[str] = None,
    runtime_mode: Optional[str] = None,
    visibility: Optional[str] = None,
    status: Optional[str] = None,
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    admin_email: str = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    q = select(ActorDefinition).order_by(desc(ActorDefinition.created_at))
    if category:
        q = q.where(ActorDefinition.category == category)
    if industry:
        q = q.where(ActorDefinition.industry == industry)
    if runtime_mode:
        q = q.where(ActorDefinition.runtime_mode == runtime_mode)
    if visibility:
        q = q.where(ActorDefinition.visibility == visibility)
    if status:
        q = q.where(ActorDefinition.status == status)
    q = q.offset(skip).limit(limit)
    rows = (await db.execute(q)).scalars().all()

    total_q = select(func.count(ActorDefinition.id))
    total = (await db.execute(total_q)).scalar() or 0

    return {
        "total": total,
        "actors": [
            {
                "id": a.id,
                "actor_id": a.actor_id,
                "name": a.name,
                "description": a.description,
                "version": a.version,
                "pack_type": a.pack_type,
                "category": a.category,
                "industry": a.industry,
                "runtime_mode": a.runtime_mode.value if a.runtime_mode else "batch",
                "risk_tier": a.risk_tier,
                "standby_enabled": a.standby_enabled,
                "visibility": a.visibility.value if a.visibility else "private",
                "marketplace_installable": a.marketplace_installable,
                "status": a.status,
                "created_at": a.created_at.isoformat() if a.created_at else None,
            }
            for a in rows
        ],
    }


@router.post("")
async def create_actor(
    req: ActorCreateRequest,
    admin_email: str = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    existing = await db.execute(
        select(ActorDefinition).where(ActorDefinition.actor_id == req.actor_id)
    )
    if existing.scalar():
        raise HTTPException(400, f"Actor '{req.actor_id}' already exists")

    mode_map = {"batch": RuntimeMode.BATCH, "standby": RuntimeMode.STANDBY, "scheduled": RuntimeMode.SCHEDULED}
    vis_map = {"private": ActorVisibility.PRIVATE, "public": ActorVisibility.PUBLIC, "unlisted": ActorVisibility.UNLISTED}

    actor = ActorDefinition(
        actor_id=req.actor_id,
        name=req.name,
        description=req.description,
        version=req.version,
        pack_type=req.pack_type,
        category=req.category,
        industry=req.industry,
        runtime_mode=mode_map.get(req.runtime_mode, RuntimeMode.BATCH),
        runtime=req.runtime,
        entrypoint=req.entrypoint,
        input_schema=req.input_schema,
        output_schema=req.output_schema,
        policy_pack=req.policy_pack,
        risk_tier=req.risk_tier,
        evidence_required=req.evidence_required,
        requires_human_review=req.requires_human_review,
        allowed_models=req.allowed_models,
        allowed_tools=req.allowed_tools,
        denied_tools=req.denied_tools,
        cost_ceiling_cents=req.cost_ceiling_cents,
        standby_enabled=req.standby_enabled,
        standby_idle_timeout_seconds=req.standby_idle_timeout_seconds,
        standby_max_requests=req.standby_max_requests,
        standby_memory_mb=req.standby_memory_mb,
        visibility=vis_map.get(req.visibility, ActorVisibility.PRIVATE),
        tenant_scoped=req.tenant_scoped,
        marketplace_installable=req.marketplace_installable,
        status="active",
    )
    db.add(actor)
    await db.commit()
    await db.refresh(actor)
    return {"status": "created", "actor_id": actor.actor_id, "id": actor.id}


@router.get("/categories")
async def actor_categories(
    admin_email: str = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    rows = (await db.execute(
        select(ActorDefinition.category, func.count(ActorDefinition.id))
        .group_by(ActorDefinition.category)
    )).all()
    return {"categories": [{"category": r[0] or "uncategorized", "count": r[1]} for r in rows]}


@router.get("/search")
async def search_actors(
    q: str = Query(""),
    admin_email: str = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    query = select(ActorDefinition).where(
        ActorDefinition.name.ilike(f"%{q}%") | ActorDefinition.description.ilike(f"%{q}%")
    ).limit(50)
    rows = (await db.execute(query)).scalars().all()
    return {
        "query": q,
        "results": [
            {"actor_id": a.actor_id, "name": a.name, "category": a.category, "status": a.status}
            for a in rows
        ],
    }


@router.get("/stats")
async def actor_stats(
    admin_email: str = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    total_actors = (await db.execute(select(func.count(ActorDefinition.id)))).scalar() or 0
    total_runs = (await db.execute(select(func.count(ActorRun.id)))).scalar() or 0
    completed = (await db.execute(
        select(func.count(ActorRun.id)).where(ActorRun.status == "completed")
    )).scalar() or 0
    failed = (await db.execute(
        select(func.count(ActorRun.id)).where(ActorRun.status == "failed")
    )).scalar() or 0
    total_cost = (await db.execute(
        select(func.coalesce(func.sum(ActorRun.cost_estimate_cents), 0))
    )).scalar() or 0
    return {
        "total_actors": total_actors,
        "total_runs": total_runs,
        "completed_runs": completed,
        "failed_runs": failed,
        "total_cost_cents": total_cost,
        "avg_cost_cents": round(total_cost / max(total_runs, 1), 2),
    }


@router.get("/{actor_id}")
async def get_actor(
    actor_id: str,
    admin_email: str = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    row = (await db.execute(
        select(ActorDefinition).where(ActorDefinition.actor_id == actor_id)
    )).scalar()
    if not row:
        raise HTTPException(404, f"Actor '{actor_id}' not found")
    return {
        "id": row.id,
        "actor_id": row.actor_id,
        "name": row.name,
        "description": row.description,
        "version": row.version,
        "pack_type": row.pack_type,
        "category": row.category,
        "industry": row.industry,
        "runtime_mode": row.runtime_mode.value if row.runtime_mode else "batch",
        "runtime": row.runtime,
        "entrypoint": row.entrypoint,
        "input_schema": row.input_schema,
        "output_schema": row.output_schema,
        "policy_pack": row.policy_pack,
        "risk_tier": row.risk_tier,
        "evidence_required": row.evidence_required,
        "requires_human_review": row.requires_human_review,
        "allowed_models": row.allowed_models,
        "allowed_tools": row.allowed_tools,
        "denied_tools": row.denied_tools,
        "cost_ceiling_cents": row.cost_ceiling_cents,
        "standby_enabled": row.standby_enabled,
        "standby_idle_timeout_seconds": row.standby_idle_timeout_seconds,
        "standby_max_requests": row.standby_max_requests,
        "standby_memory_mb": row.standby_memory_mb,
        "visibility": row.visibility.value if row.visibility else "private",
        "tenant_scoped": row.tenant_scoped,
        "marketplace_installable": row.marketplace_installable,
        "status": row.status,
        "created_at": row.created_at.isoformat() if row.created_at else None,
    }


@router.patch("/{actor_id}")
async def update_actor(
    actor_id: str,
    updates: dict,
    admin_email: str = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    row = (await db.execute(
        select(ActorDefinition).where(ActorDefinition.actor_id == actor_id)
    )).scalar()
    if not row:
        raise HTTPException(404, f"Actor '{actor_id}' not found")
    allowed = {
        "name", "description", "version", "category", "industry", "entrypoint",
        "input_schema", "output_schema", "policy_pack", "risk_tier",
        "evidence_required", "requires_human_review", "cost_ceiling_cents",
        "standby_enabled", "standby_idle_timeout_seconds", "standby_max_requests",
        "standby_memory_mb", "marketplace_installable", "status", "config",
    }
    for k, v in updates.items():
        if k in allowed:
            setattr(row, k, v)
    await db.commit()
    return {"status": "updated", "actor_id": actor_id}


@router.delete("/{actor_id}")
async def delete_actor(
    actor_id: str,
    admin_email: str = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    row = (await db.execute(
        select(ActorDefinition).where(ActorDefinition.actor_id == actor_id)
    )).scalar()
    if not row:
        raise HTTPException(404, f"Actor '{actor_id}' not found")
    await db.delete(row)
    await db.commit()
    return {"status": "deleted", "actor_id": actor_id}


# ---------------------------------------------------------------------------
# Actor runs
# ---------------------------------------------------------------------------

@router.post("/{actor_id}/run")
async def run_actor(
    actor_id: str,
    req: ActorRunRequest,
    admin_email: str = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    actor = (await db.execute(
        select(ActorDefinition).where(ActorDefinition.actor_id == actor_id)
    )).scalar()
    if not actor:
        raise HTTPException(404, f"Actor '{actor_id}' not found")

    input_str = str(req.input_data or {})
    input_hash = hashlib.sha256(input_str.encode()).hexdigest()[:16]

    run = ActorRun(
        actor_def_id=actor.id,
        actor_id=actor_id,
        runtime_mode=actor.runtime_mode,
        workspace_id=req.workspace_id,
        tenant_id=req.tenant_id,
        user_id=req.user_id,
        agent_id=req.agent_id,
        input_hash=input_hash,
        input_data=req.input_data,
        risk_tier=req.risk_tier or actor.risk_tier,
        model_provider=req.model_provider,
        status="running",
        started_at=datetime.utcnow(),
    )
    db.add(run)
    await db.commit()
    await db.refresh(run)
    return {"status": "started", "run_id": run.id, "actor_id": actor_id}


@router.get("/{actor_id}/runs")
async def list_actor_runs(
    actor_id: str,
    status: Optional[str] = None,
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    admin_email: str = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    q = select(ActorRun).where(ActorRun.actor_id == actor_id).order_by(desc(ActorRun.created_at))
    if status:
        q = q.where(ActorRun.status == status)
    q = q.offset(skip).limit(limit)
    rows = (await db.execute(q)).scalars().all()
    return {
        "actor_id": actor_id,
        "runs": [
            {
                "id": r.id,
                "status": r.status,
                "runtime_mode": r.runtime_mode.value if r.runtime_mode else "batch",
                "cost_estimate_cents": r.cost_estimate_cents,
                "tokens_used": r.tokens_used,
                "latency_ms": r.latency_ms,
                "started_at": r.started_at.isoformat() if r.started_at else None,
                "ended_at": r.ended_at.isoformat() if r.ended_at else None,
            }
            for r in rows
        ],
    }


@router.get("/runs/{run_id}")
async def get_actor_run(
    run_id: str,
    admin_email: str = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    run = (await db.execute(select(ActorRun).where(ActorRun.id == run_id))).scalar()
    if not run:
        raise HTTPException(404, f"Run '{run_id}' not found")
    return {
        "id": run.id,
        "actor_id": run.actor_id,
        "runtime_mode": run.runtime_mode.value if run.runtime_mode else "batch",
        "workspace_id": run.workspace_id,
        "tenant_id": run.tenant_id,
        "user_id": run.user_id,
        "agent_id": run.agent_id,
        "input_hash": run.input_hash,
        "output_hash": run.output_hash,
        "policy_result": run.policy_result,
        "risk_tier": run.risk_tier,
        "model_provider": run.model_provider,
        "tools_used": run.tools_used,
        "cost_estimate_cents": run.cost_estimate_cents,
        "latency_ms": run.latency_ms,
        "tokens_used": run.tokens_used,
        "evidence_id": run.evidence_id,
        "proof_hash": run.proof_hash,
        "audit_hash": run.audit_hash,
        "status": run.status,
        "error_message": run.error_message,
        "started_at": run.started_at.isoformat() if run.started_at else None,
        "ended_at": run.ended_at.isoformat() if run.ended_at else None,
    }


@router.get("/runs/{run_id}/output")
async def get_actor_run_output(
    run_id: str,
    admin_email: str = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    run = (await db.execute(select(ActorRun).where(ActorRun.id == run_id))).scalar()
    if not run:
        raise HTTPException(404, f"Run '{run_id}' not found")
    return {
        "run_id": run.id,
        "actor_id": run.actor_id,
        "output_data": run.output_data,
        "output_hash": run.output_hash,
        "status": run.status,
    }


@router.get("/runs/{run_id}/evidence")
async def get_actor_run_evidence(
    run_id: str,
    admin_email: str = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    run = (await db.execute(select(ActorRun).where(ActorRun.id == run_id))).scalar()
    if not run:
        raise HTTPException(404, f"Run '{run_id}' not found")
    return {
        "run_id": run.id,
        "actor_id": run.actor_id,
        "evidence_id": run.evidence_id,
        "proof_hash": run.proof_hash,
        "audit_hash": run.audit_hash,
        "policy_result": run.policy_result,
        "risk_tier": run.risk_tier,
    }


@router.patch("/runs/{run_id}/complete")
async def complete_actor_run(
    run_id: str,
    req: ActorRunCompleteRequest,
    admin_email: str = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    run = (await db.execute(select(ActorRun).where(ActorRun.id == run_id))).scalar()
    if not run:
        raise HTTPException(404, f"Run '{run_id}' not found")

    run.status = req.status
    run.output_data = req.output_data
    run.policy_result = req.policy_result
    run.tools_used = req.tools_used
    run.cost_estimate_cents = req.cost_estimate_cents
    run.tokens_used = req.tokens_used
    run.latency_ms = req.latency_ms
    run.error_message = req.error_message
    run.ended_at = datetime.utcnow()

    output_str = str(req.output_data or {})
    run.output_hash = hashlib.sha256(output_str.encode()).hexdigest()[:16]

    proof_payload = f"{run.id}:{run.actor_id}:{run.input_hash}:{run.output_hash}:{run.status}"
    run.proof_hash = hashlib.sha256(proof_payload.encode()).hexdigest()
    run.audit_hash = hashlib.sha256(f"audit:{proof_payload}:{run.ended_at}".encode()).hexdigest()

    await db.commit()
    return {
        "status": "completed",
        "run_id": run.id,
        "proof_hash": run.proof_hash,
        "audit_hash": run.audit_hash,
    }


# ---------------------------------------------------------------------------
# Publish to marketplace
# ---------------------------------------------------------------------------

@router.post("/{actor_id}/publish")
async def publish_actor(
    actor_id: str,
    admin_email: str = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    actor = (await db.execute(
        select(ActorDefinition).where(ActorDefinition.actor_id == actor_id)
    )).scalar()
    if not actor:
        raise HTTPException(404, f"Actor '{actor_id}' not found")
    actor.marketplace_installable = True
    actor.visibility = ActorVisibility.PUBLIC
    await db.commit()
    return {"status": "published", "actor_id": actor_id, "marketplace_installable": True}


# ---------------------------------------------------------------------------
# Standby controls
# ---------------------------------------------------------------------------

@router.get("/{actor_id}/standby/status")
async def standby_status(
    actor_id: str,
    admin_email: str = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    actor = (await db.execute(
        select(ActorDefinition).where(ActorDefinition.actor_id == actor_id)
    )).scalar()
    if not actor:
        raise HTTPException(404, f"Actor '{actor_id}' not found")
    return {
        "actor_id": actor_id,
        "standby_enabled": actor.standby_enabled,
        "runtime_mode": actor.runtime_mode.value if actor.runtime_mode else "batch",
        "readiness_path": actor.standby_readiness_path,
        "idle_timeout_seconds": actor.standby_idle_timeout_seconds,
        "max_requests": actor.standby_max_requests,
        "memory_mb": actor.standby_memory_mb,
    }


@router.post("/{actor_id}/standby/start")
async def start_standby(
    actor_id: str,
    admin_email: str = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    actor = (await db.execute(
        select(ActorDefinition).where(ActorDefinition.actor_id == actor_id)
    )).scalar()
    if not actor:
        raise HTTPException(404, f"Actor '{actor_id}' not found")
    actor.standby_enabled = True
    actor.runtime_mode = RuntimeMode.STANDBY
    await db.commit()
    return {"status": "standby_started", "actor_id": actor_id}


@router.post("/{actor_id}/standby/stop")
async def stop_standby(
    actor_id: str,
    admin_email: str = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    actor = (await db.execute(
        select(ActorDefinition).where(ActorDefinition.actor_id == actor_id)
    )).scalar()
    if not actor:
        raise HTTPException(404, f"Actor '{actor_id}' not found")
    actor.standby_enabled = False
    actor.runtime_mode = RuntimeMode.BATCH
    await db.commit()
    return {"status": "standby_stopped", "actor_id": actor_id}


# ---------------------------------------------------------------------------
# Schema inspection
# ---------------------------------------------------------------------------

@router.get("/{actor_id}/schema/input")
async def get_input_schema(
    actor_id: str,
    admin_email: str = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    actor = (await db.execute(
        select(ActorDefinition).where(ActorDefinition.actor_id == actor_id)
    )).scalar()
    if not actor:
        raise HTTPException(404, f"Actor '{actor_id}' not found")
    return {"actor_id": actor_id, "input_schema": actor.input_schema}


@router.get("/{actor_id}/schema/output")
async def get_output_schema(
    actor_id: str,
    admin_email: str = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    actor = (await db.execute(
        select(ActorDefinition).where(ActorDefinition.actor_id == actor_id)
    )).scalar()
    if not actor:
        raise HTTPException(404, f"Actor '{actor_id}' not found")
    return {"actor_id": actor_id, "output_schema": actor.output_schema}


@router.get("/{actor_id}/policy")
async def get_actor_policy(
    actor_id: str,
    admin_email: str = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    actor = (await db.execute(
        select(ActorDefinition).where(ActorDefinition.actor_id == actor_id)
    )).scalar()
    if not actor:
        raise HTTPException(404, f"Actor '{actor_id}' not found")
    return {
        "actor_id": actor_id,
        "policy_pack": actor.policy_pack,
        "risk_tier": actor.risk_tier,
        "evidence_required": actor.evidence_required,
        "requires_human_review": actor.requires_human_review,
        "allowed_models": actor.allowed_models,
        "allowed_tools": actor.allowed_tools,
        "denied_tools": actor.denied_tools,
        "cost_ceiling_cents": actor.cost_ceiling_cents,
    }
