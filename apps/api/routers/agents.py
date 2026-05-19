"""Agent Workforce Router — full CRUD for agent registry, runs, governance.

Endpoints cover:
- Agent registry (definitions, fleet, groups)
- Agent runs (history, create, complete)
- Decision frames (create, list, replay)
- Signals (create, list, route)
- Violations (record, list, resolve)
- Rewards (grant, list)
- Council votes (cast, list, tally)
- Freeze/intel reports (list, detail)
- Evidence artifacts (create, list)
- Monthly proof report
"""

import hashlib
import json
import logging
from datetime import datetime, timedelta
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select, func, and_
from sqlalchemy.ext.asyncio import AsyncSession

from core.config.settings import settings
from core.database.database import get_db
from core.security.auth import require_admin
from db.models import (
    AgentDefinition,
    AgentRun,
    DecisionFrame,
    AgentSignal,
    AgentViolation,
    AgentReward,
    AgentCouncilVote,
    IntelFreezeReport,
    EvidenceArtifact,
)

router = APIRouter()
logger = logging.getLogger(__name__)

ADMIN_EMAIL = settings.ADMIN_EMAIL




# ---------------------------------------------------------------------------
# Agent Registry — definitions
# ---------------------------------------------------------------------------


@router.get("/registry")
async def list_agents(
    group: Optional[str] = None,
    status: Optional[str] = None,
    committee: Optional[str] = None,
    skip: int = Query(0, ge=0),
    limit: int = Query(200, ge=1, le=500),
    admin_email: str = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """List all agent definitions with optional filters."""
    q = select(AgentDefinition).order_by(AgentDefinition.agent_number)
    if group:
        q = q.where(AgentDefinition.group == group)
    if status:
        q = q.where(AgentDefinition.status == status)
    if committee:
        q = q.where(AgentDefinition.committee == committee)
    result = await db.execute(q.offset(skip).limit(limit))
    agents = result.scalars().all()
    return {
        "agents": [
            {
                "id": a.id,
                "agent_number": a.agent_number,
                "name": a.name,
                "codename": a.codename,
                "group": a.group,
                "phase": a.phase,
                "committee": a.committee,
                "priority": a.priority,
                "capabilities": a.capabilities,
                "status": a.status.value if a.status else "standby",
                "is_control_agent": a.is_control_agent,
                "rank_level": a.rank_level,
                "voting_weight": a.voting_weight,
            }
            for a in agents
        ],
        "total": len(agents),
        "timestamp": datetime.utcnow().isoformat(),
    }


@router.get("/registry/{agent_number}")
async def get_agent(
    agent_number: int,
    admin_email: str = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Get a single agent definition by number."""
    result = await db.execute(
        select(AgentDefinition).where(
            AgentDefinition.agent_number == agent_number
        )
    )
    agent = result.scalars().first()
    if not agent:
        raise HTTPException(status_code=404, detail=f"Agent {agent_number} not found")
    return {
        "id": agent.id,
        "agent_number": agent.agent_number,
        "name": agent.name,
        "codename": agent.codename,
        "group": agent.group,
        "phase": agent.phase,
        "committee": agent.committee,
        "priority": agent.priority,
        "mission": agent.mission,
        "capabilities": agent.capabilities,
        "tools_allowed": agent.tools_allowed,
        "tools_denied": agent.tools_denied,
        "guardrail_ids": agent.guardrail_ids,
        "voting_weight": agent.voting_weight,
        "rank_level": agent.rank_level,
        "status": agent.status.value if agent.status else "standby",
        "is_control_agent": agent.is_control_agent,
        "config": agent.config,
        "created_at": agent.created_at.isoformat() if agent.created_at else None,
    }


@router.get("/registry/{agent_number}/mission")
async def get_agent_mission(
    agent_number: int,
    admin_email: str = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Get just the mission text for an agent."""
    result = await db.execute(
        select(AgentDefinition).where(
            AgentDefinition.agent_number == agent_number
        )
    )
    agent = result.scalars().first()
    if not agent:
        raise HTTPException(status_code=404, detail=f"Agent {agent_number} not found")
    return {
        "agent_number": agent.agent_number,
        "codename": agent.codename,
        "mission": agent.mission,
    }


@router.patch("/registry/{agent_number}/status")
async def update_agent_status(
    agent_number: int,
    new_status: str = Query(...),
    admin_email: str = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Update an agent's operational status."""
    valid = {"active", "standby", "frozen", "decommissioned", "penalty"}
    if new_status not in valid:
        raise HTTPException(status_code=400, detail=f"Invalid status: {new_status}")
    result = await db.execute(
        select(AgentDefinition).where(
            AgentDefinition.agent_number == agent_number
        )
    )
    agent = result.scalars().first()
    if not agent:
        raise HTTPException(status_code=404, detail=f"Agent {agent_number} not found")
    agent.status = new_status
    await db.commit()
    return {"agent_number": agent_number, "status": new_status}


# ---------------------------------------------------------------------------
# Fleet — aggregated views
# ---------------------------------------------------------------------------


@router.get("/fleet")
async def agent_fleet(
    admin_email: str = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Fleet overview — agents by group with counts and status."""
    result = await db.execute(
        select(
            AgentDefinition.group,
            AgentDefinition.status,
            func.count().label("cnt"),
        ).group_by(AgentDefinition.group, AgentDefinition.status)
    )
    rows = result.all()
    groups: dict = {}
    for group_name, status, count in rows:
        if group_name not in groups:
            groups[group_name] = {"name": group_name, "total": 0, "active": 0, "standby": 0, "frozen": 0, "penalty": 0}
        groups[group_name]["total"] += count
        status_val = status.value if hasattr(status, "value") else str(status)
        if status_val in groups[group_name]:
            groups[group_name][status_val] += count
    total = sum(g["total"] for g in groups.values())
    active = sum(g["active"] for g in groups.values())
    return {
        "total_agents": total,
        "active": active,
        "standby": total - active,
        "groups": list(groups.values()),
        "agent_count_model": {
            "operational": 114,
            "control_council": 6,
            "special_governance": 10,
            "total": 130,
        },
        "timestamp": datetime.utcnow().isoformat(),
    }


@router.get("/fleet/capabilities")
async def fleet_capabilities(
    admin_email: str = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """List all unique capabilities across the fleet."""
    result = await db.execute(
        select(AgentDefinition.capabilities).where(
            AgentDefinition.capabilities.isnot(None)
        )
    )
    all_caps: set = set()
    for (caps,) in result.all():
        if isinstance(caps, list):
            all_caps.update(caps)
    return {"capabilities": sorted(all_caps), "timestamp": datetime.utcnow().isoformat()}


@router.get("/fleet/committees")
async def fleet_committees(
    admin_email: str = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Agent counts by committee."""
    result = await db.execute(
        select(AgentDefinition.committee, func.count().label("cnt"))
        .group_by(AgentDefinition.committee)
    )
    return {
        "committees": [{"name": c, "count": n} for c, n in result.all()],
        "timestamp": datetime.utcnow().isoformat(),
    }


# ---------------------------------------------------------------------------
# Agent Runs — execution history
# ---------------------------------------------------------------------------


@router.get("/runs")
async def list_runs(
    agent_number: Optional[int] = None,
    group: Optional[str] = None,
    status: Optional[str] = None,
    hours: int = Query(24, ge=1, le=720),
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=500),
    admin_email: str = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """List agent runs with filters."""
    since = datetime.utcnow() - timedelta(hours=hours)
    q = select(AgentRun).where(AgentRun.started_at >= since).order_by(AgentRun.started_at.desc())
    if agent_number is not None:
        q = q.where(AgentRun.agent_number == agent_number)
    if group:
        q = q.where(AgentRun.group == group)
    if status:
        q = q.where(AgentRun.status == status)
    result = await db.execute(q.offset(skip).limit(limit))
    runs = result.scalars().all()
    return {
        "runs": [
            {
                "id": r.id,
                "agent_number": r.agent_number,
                "agent_name": r.agent_name,
                "group": r.group,
                "task": r.task,
                "status": r.status,
                "cost_cents": r.cost_cents,
                "tokens_used": r.tokens_used,
                "errors": r.errors,
                "blocked_mutations": r.blocked_mutations,
                "approval_required": r.approval_required,
                "evidence_id": r.evidence_id,
                "audit_hash": r.audit_hash,
                "started_at": r.started_at.isoformat() if r.started_at else None,
                "ended_at": r.ended_at.isoformat() if r.ended_at else None,
            }
            for r in runs
        ],
        "count": len(runs),
        "period_hours": hours,
        "timestamp": datetime.utcnow().isoformat(),
    }


@router.post("/runs")
async def create_run(
    agent_number: int = Query(...),
    task: str = Query(...),
    admin_email: str = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Start a new agent run."""
    agent_result = await db.execute(
        select(AgentDefinition).where(
            AgentDefinition.agent_number == agent_number
        )
    )
    agent = agent_result.scalars().first()
    if not agent:
        raise HTTPException(status_code=404, detail=f"Agent {agent_number} not found")
    run = AgentRun(
        agent_id=agent.id,
        agent_number=agent.agent_number,
        agent_name=agent.name,
        group=agent.group,
        task=task,
        status="running",
    )
    db.add(run)
    await db.commit()
    await db.refresh(run)
    return {"run_id": run.id, "agent_number": agent_number, "status": "running"}


@router.patch("/runs/{run_id}/complete")
async def complete_run(
    run_id: str,
    status: str = Query("completed"),
    cost_cents: int = Query(0),
    tokens_used: int = Query(0),
    admin_email: str = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Complete an agent run with results."""
    result = await db.execute(select(AgentRun).where(AgentRun.id == run_id))
    run = result.scalars().first()
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")
    run.status = status
    run.cost_cents = cost_cents
    run.tokens_used = tokens_used
    run.ended_at = datetime.utcnow()
    run.audit_hash = hashlib.sha256(
        json.dumps({
            "run_id": run.id,
            "agent": run.agent_number,
            "task": run.task,
            "status": status,
            "ended_at": run.ended_at.isoformat(),
        }).encode()
    ).hexdigest()
    await db.commit()
    return {"run_id": run.id, "status": status, "audit_hash": run.audit_hash}


@router.get("/runs/stats")
async def run_stats(
    hours: int = Query(24, ge=1, le=720),
    admin_email: str = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Aggregated run statistics."""
    since = datetime.utcnow() - timedelta(hours=hours)
    total = (
        await db.execute(
            select(func.count()).select_from(AgentRun).where(AgentRun.started_at >= since)
        )
    ).scalar() or 0
    completed = (
        await db.execute(
            select(func.count())
            .select_from(AgentRun)
            .where(and_(AgentRun.started_at >= since, AgentRun.status == "completed"))
        )
    ).scalar() or 0
    failed = (
        await db.execute(
            select(func.count())
            .select_from(AgentRun)
            .where(and_(AgentRun.started_at >= since, AgentRun.status == "failed"))
        )
    ).scalar() or 0
    total_cost = (
        await db.execute(
            select(func.coalesce(func.sum(AgentRun.cost_cents), 0)).where(
                AgentRun.started_at >= since
            )
        )
    ).scalar() or 0
    return {
        "period_hours": hours,
        "total_runs": total,
        "completed": completed,
        "failed": failed,
        "running": total - completed - failed,
        "total_cost_cents": total_cost,
        "avg_cost_cents": round(total_cost / max(total, 1)),
        "timestamp": datetime.utcnow().isoformat(),
    }


# ---------------------------------------------------------------------------
# Decision Frames
# ---------------------------------------------------------------------------


@router.get("/decision-frames")
async def list_decision_frames(
    agent_number: Optional[int] = None,
    risk_tier: Optional[str] = None,
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    admin_email: str = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """List decision frames."""
    q = select(DecisionFrame).order_by(DecisionFrame.created_at.desc())
    if risk_tier:
        q = q.where(DecisionFrame.risk_tier == risk_tier)
    result = await db.execute(q.offset(skip).limit(limit))
    frames = result.scalars().all()
    return {
        "frames": [
            {
                "id": f.id,
                "actor": f.actor,
                "objective": f.objective,
                "risk_tier": f.risk_tier,
                "proof_hash": f.proof_hash,
                "replay_status": f.replay_status,
                "cost_estimate_cents": f.cost_estimate_cents,
                "created_at": f.created_at.isoformat() if f.created_at else None,
            }
            for f in frames
        ],
        "count": len(frames),
        "timestamp": datetime.utcnow().isoformat(),
    }


@router.post("/decision-frames")
async def create_decision_frame(
    agent_number: int = Query(...),
    objective: str = Query(...),
    risk_tier: str = Query("low"),
    cost_estimate_cents: int = Query(0),
    admin_email: str = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Create a new decision frame."""
    agent_result = await db.execute(
        select(AgentDefinition).where(
            AgentDefinition.agent_number == agent_number
        )
    )
    agent = agent_result.scalars().first()
    if not agent:
        raise HTTPException(status_code=404, detail=f"Agent {agent_number} not found")
    frame = DecisionFrame(
        agent_id=agent.id,
        actor=agent.codename,
        objective=objective,
        risk_tier=risk_tier,
        cost_estimate_cents=cost_estimate_cents,
        tools_allowed=agent.tools_allowed or [],
        tools_denied=agent.tools_denied or [],
    )
    db.add(frame)
    await db.commit()
    await db.refresh(frame)
    frame.proof_hash = hashlib.sha256(
        json.dumps({
            "frame_id": frame.id,
            "actor": frame.actor,
            "objective": objective,
            "risk_tier": risk_tier,
            "created_at": frame.created_at.isoformat(),
        }).encode()
    ).hexdigest()
    await db.commit()
    return {"frame_id": frame.id, "proof_hash": frame.proof_hash}


# ---------------------------------------------------------------------------
# Signals
# ---------------------------------------------------------------------------


@router.get("/signals")
async def list_signals(
    signal_type: Optional[str] = None,
    status: Optional[str] = None,
    hours: int = Query(24, ge=1, le=720),
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=500),
    admin_email: str = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """List agent signals."""
    since = datetime.utcnow() - timedelta(hours=hours)
    q = select(AgentSignal).where(AgentSignal.created_at >= since).order_by(AgentSignal.created_at.desc())
    if signal_type:
        q = q.where(AgentSignal.signal_type == signal_type)
    if status:
        q = q.where(AgentSignal.status == status)
    result = await db.execute(q.offset(skip).limit(limit))
    signals = result.scalars().all()
    return {
        "signals": [
            {
                "id": s.id,
                "signal_type": s.signal_type,
                "severity": s.severity,
                "source": s.source,
                "summary": s.summary,
                "score": s.score,
                "status": s.status,
                "routed_to": s.routed_to,
                "created_at": s.created_at.isoformat() if s.created_at else None,
            }
            for s in signals
        ],
        "count": len(signals),
        "timestamp": datetime.utcnow().isoformat(),
    }


@router.post("/signals")
async def create_signal(
    agent_number: int = Query(...),
    signal_type: str = Query(...),
    source: str = Query(...),
    summary: str = Query(...),
    severity: str = Query("info"),
    score: float = Query(0.0),
    admin_email: str = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Record a new agent signal."""
    agent_result = await db.execute(
        select(AgentDefinition).where(
            AgentDefinition.agent_number == agent_number
        )
    )
    agent = agent_result.scalars().first()
    if not agent:
        raise HTTPException(status_code=404, detail=f"Agent {agent_number} not found")
    signal = AgentSignal(
        agent_id=agent.id,
        signal_type=signal_type,
        severity=severity,
        source=source,
        summary=summary,
        score=score,
    )
    db.add(signal)
    await db.commit()
    await db.refresh(signal)
    return {"signal_id": signal.id, "signal_type": signal_type}


# ---------------------------------------------------------------------------
# Violations
# ---------------------------------------------------------------------------


@router.get("/violations")
async def list_violations(
    agent_number: Optional[int] = None,
    resolved: Optional[bool] = None,
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=500),
    admin_email: str = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """List guardrail violations."""
    q = select(AgentViolation).order_by(AgentViolation.created_at.desc())
    if resolved is not None:
        q = q.where(AgentViolation.resolved == resolved)
    result = await db.execute(q.offset(skip).limit(limit))
    violations = result.scalars().all()
    return {
        "violations": [
            {
                "id": v.id,
                "guardrail_id": v.guardrail_id,
                "guardrail_name": v.guardrail_name,
                "severity": v.severity,
                "description": v.description,
                "penalty_applied": v.penalty_applied,
                "penalty_points": v.penalty_points,
                "resolved": v.resolved,
                "created_at": v.created_at.isoformat() if v.created_at else None,
            }
            for v in violations
        ],
        "count": len(violations),
        "timestamp": datetime.utcnow().isoformat(),
    }


@router.post("/violations")
async def record_violation(
    agent_number: int = Query(...),
    guardrail_id: str = Query(...),
    guardrail_name: str = Query(...),
    severity: str = Query(...),
    description: str = Query(...),
    penalty_applied: Optional[str] = None,
    penalty_points: int = Query(0),
    admin_email: str = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Record a guardrail violation."""
    agent_result = await db.execute(
        select(AgentDefinition).where(
            AgentDefinition.agent_number == agent_number
        )
    )
    agent = agent_result.scalars().first()
    if not agent:
        raise HTTPException(status_code=404, detail=f"Agent {agent_number} not found")
    violation = AgentViolation(
        agent_id=agent.id,
        guardrail_id=guardrail_id,
        guardrail_name=guardrail_name,
        severity=severity,
        description=description,
        penalty_applied=penalty_applied,
        penalty_points=penalty_points,
    )
    db.add(violation)
    await db.commit()
    await db.refresh(violation)
    return {"violation_id": violation.id}


@router.patch("/violations/{violation_id}/resolve")
async def resolve_violation(
    violation_id: str,
    admin_email: str = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Mark a violation as resolved."""
    result = await db.execute(
        select(AgentViolation).where(AgentViolation.id == violation_id)
    )
    v = result.scalars().first()
    if not v:
        raise HTTPException(status_code=404, detail="Violation not found")
    v.resolved = True
    await db.commit()
    return {"violation_id": violation_id, "resolved": True}


# ---------------------------------------------------------------------------
# Rewards
# ---------------------------------------------------------------------------


@router.get("/rewards")
async def list_rewards(
    agent_number: Optional[int] = None,
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=500),
    admin_email: str = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """List agent rewards/incentives."""
    q = select(AgentReward).order_by(AgentReward.created_at.desc())
    result = await db.execute(q.offset(skip).limit(limit))
    rewards = result.scalars().all()
    return {
        "rewards": [
            {
                "id": r.id,
                "reward_type": r.reward_type,
                "description": r.description,
                "points": r.points,
                "rank_change": r.rank_change,
                "voting_weight_change": r.voting_weight_change,
                "created_at": r.created_at.isoformat() if r.created_at else None,
            }
            for r in rewards
        ],
        "count": len(rewards),
        "timestamp": datetime.utcnow().isoformat(),
    }


@router.post("/rewards")
async def grant_reward(
    agent_number: int = Query(...),
    reward_type: str = Query(...),
    description: str = Query(...),
    points: int = Query(0),
    admin_email: str = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Grant a reward to an agent."""
    agent_result = await db.execute(
        select(AgentDefinition).where(
            AgentDefinition.agent_number == agent_number
        )
    )
    agent = agent_result.scalars().first()
    if not agent:
        raise HTTPException(status_code=404, detail=f"Agent {agent_number} not found")
    reward = AgentReward(
        agent_id=agent.id,
        reward_type=reward_type,
        description=description,
        points=points,
    )
    db.add(reward)
    await db.commit()
    await db.refresh(reward)
    return {"reward_id": reward.id}


# ---------------------------------------------------------------------------
# Council Votes
# ---------------------------------------------------------------------------


@router.get("/council/votes")
async def list_council_votes(
    proposal_id: Optional[str] = None,
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=500),
    admin_email: str = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """List sovereign council votes."""
    q = select(AgentCouncilVote).order_by(AgentCouncilVote.created_at.desc())
    if proposal_id:
        q = q.where(AgentCouncilVote.proposal_id == proposal_id)
    result = await db.execute(q.offset(skip).limit(limit))
    votes = result.scalars().all()
    return {
        "votes": [
            {
                "id": v.id,
                "proposal_id": v.proposal_id,
                "proposal_summary": v.proposal_summary,
                "vote": v.vote,
                "voting_weight": v.voting_weight,
                "reasoning": v.reasoning,
                "created_at": v.created_at.isoformat() if v.created_at else None,
            }
            for v in votes
        ],
        "count": len(votes),
        "timestamp": datetime.utcnow().isoformat(),
    }


@router.post("/council/votes")
async def cast_vote(
    agent_number: int = Query(...),
    proposal_id: str = Query(...),
    proposal_summary: str = Query(...),
    vote: str = Query(...),
    reasoning: Optional[str] = None,
    admin_email: str = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Cast a council vote."""
    agent_result = await db.execute(
        select(AgentDefinition).where(
            AgentDefinition.agent_number == agent_number
        )
    )
    agent = agent_result.scalars().first()
    if not agent:
        raise HTTPException(status_code=404, detail=f"Agent {agent_number} not found")
    council_vote = AgentCouncilVote(
        agent_id=agent.id,
        proposal_id=proposal_id,
        proposal_summary=proposal_summary,
        vote=vote,
        voting_weight=agent.voting_weight,
        reasoning=reasoning,
    )
    db.add(council_vote)
    await db.commit()
    await db.refresh(council_vote)
    return {"vote_id": council_vote.id}


@router.get("/council/tally/{proposal_id}")
async def tally_votes(
    proposal_id: str,
    admin_email: str = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Tally votes for a proposal (weighted)."""
    result = await db.execute(
        select(AgentCouncilVote).where(
            AgentCouncilVote.proposal_id == proposal_id
        )
    )
    votes = result.scalars().all()
    approve_weight = sum(v.voting_weight for v in votes if v.vote == "approve")
    reject_weight = sum(v.voting_weight for v in votes if v.vote == "reject")
    abstain_weight = sum(v.voting_weight for v in votes if v.vote == "abstain")
    total_weight = approve_weight + reject_weight + abstain_weight
    return {
        "proposal_id": proposal_id,
        "total_votes": len(votes),
        "approve_weight": approve_weight,
        "reject_weight": reject_weight,
        "abstain_weight": abstain_weight,
        "result": "approved" if approve_weight > reject_weight else "rejected",
        "quorum_met": total_weight > 0,
        "timestamp": datetime.utcnow().isoformat(),
    }


# ---------------------------------------------------------------------------
# Intel Freeze Reports
# ---------------------------------------------------------------------------


@router.get("/freeze-reports")
async def list_freeze_reports(
    status: Optional[str] = None,
    admin_email: str = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """List FREEZE_INTEL reports."""
    q = select(IntelFreezeReport).order_by(IntelFreezeReport.frozen_at.desc())
    if status:
        q = q.where(IntelFreezeReport.status == status)
    result = await db.execute(q.limit(100))
    reports = result.scalars().all()
    return {
        "reports": [
            {
                "id": r.id,
                "initiated_by": r.initiated_by,
                "snapshot_id": r.snapshot_id,
                "reason": r.reason,
                "blocked_mutations": r.blocked_mutations,
                "blocked_agents": r.blocked_agents,
                "status": r.status,
                "frozen_at": r.frozen_at.isoformat() if r.frozen_at else None,
                "unfrozen_at": r.unfrozen_at.isoformat() if r.unfrozen_at else None,
            }
            for r in reports
        ],
        "count": len(reports),
        "timestamp": datetime.utcnow().isoformat(),
    }


# ---------------------------------------------------------------------------
# Evidence Artifacts
# ---------------------------------------------------------------------------


@router.get("/evidence")
async def list_evidence(
    artifact_type: Optional[str] = None,
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=500),
    admin_email: str = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """List evidence artifacts."""
    q = select(EvidenceArtifact).order_by(EvidenceArtifact.created_at.desc())
    if artifact_type:
        q = q.where(EvidenceArtifact.artifact_type == artifact_type)
    result = await db.execute(q.offset(skip).limit(limit))
    artifacts = result.scalars().all()
    return {
        "artifacts": [
            {
                "id": a.id,
                "artifact_type": a.artifact_type,
                "title": a.title,
                "description": a.description,
                "content_hash": a.content_hash,
                "created_at": a.created_at.isoformat() if a.created_at else None,
            }
            for a in artifacts
        ],
        "count": len(artifacts),
        "timestamp": datetime.utcnow().isoformat(),
    }


@router.post("/evidence")
async def create_evidence(
    artifact_type: str = Query(...),
    title: str = Query(...),
    content: str = Query(...),
    agent_number: Optional[int] = None,
    admin_email: str = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Create an evidence artifact with SHA-256 hash."""
    content_hash = hashlib.sha256(content.encode()).hexdigest()
    agent_id = None
    if agent_number is not None:
        agent_result = await db.execute(
            select(AgentDefinition).where(
                AgentDefinition.agent_number == agent_number
            )
        )
        agent = agent_result.scalars().first()
        if agent:
            agent_id = agent.id
    artifact = EvidenceArtifact(
        agent_id=agent_id,
        artifact_type=artifact_type,
        title=title,
        content_hash=content_hash,
    )
    db.add(artifact)
    await db.commit()
    await db.refresh(artifact)
    return {"artifact_id": artifact.id, "content_hash": content_hash}


# ---------------------------------------------------------------------------
# Monthly Proof Report
# ---------------------------------------------------------------------------


@router.get("/monthly-report")
async def monthly_proof_report(
    days: int = Query(30, ge=1, le=90),
    admin_email: str = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Generate monthly agent proof report."""
    since = datetime.utcnow() - timedelta(days=days)

    total_runs = (
        await db.execute(
            select(func.count()).select_from(AgentRun).where(
                AgentRun.started_at >= since
            )
        )
    ).scalar() or 0
    completed_runs = (
        await db.execute(
            select(func.count()).select_from(AgentRun).where(
                and_(AgentRun.started_at >= since, AgentRun.status == "completed")
            )
        )
    ).scalar() or 0
    failed_runs = (
        await db.execute(
            select(func.count()).select_from(AgentRun).where(
                and_(AgentRun.started_at >= since, AgentRun.status == "failed")
            )
        )
    ).scalar() or 0
    total_cost = (
        await db.execute(
            select(func.coalesce(func.sum(AgentRun.cost_cents), 0)).where(
                AgentRun.started_at >= since
            )
        )
    ).scalar() or 0
    total_violations = (
        await db.execute(
            select(func.count()).select_from(AgentViolation).where(
                AgentViolation.created_at >= since
            )
        )
    ).scalar() or 0
    total_signals = (
        await db.execute(
            select(func.count()).select_from(AgentSignal).where(
                AgentSignal.created_at >= since
            )
        )
    ).scalar() or 0
    total_evidence = (
        await db.execute(
            select(func.count()).select_from(EvidenceArtifact).where(
                EvidenceArtifact.created_at >= since
            )
        )
    ).scalar() or 0
    total_freezes = (
        await db.execute(
            select(func.count()).select_from(IntelFreezeReport).where(
                IntelFreezeReport.frozen_at >= since
            )
        )
    ).scalar() or 0
    total_council_votes = (
        await db.execute(
            select(func.count()).select_from(AgentCouncilVote).where(
                AgentCouncilVote.created_at >= since
            )
        )
    ).scalar() or 0

    return {
        "report": "MONTHLY_AGENT_PROOF_REPORT",
        "period_days": days,
        "period_start": since.isoformat(),
        "period_end": datetime.utcnow().isoformat(),
        "agent_count_model": {
            "operational": 114,
            "control_council": 6,
            "special_governance": 10,
            "total": 130,
        },
        "runs": {
            "total": total_runs,
            "completed": completed_runs,
            "failed": failed_runs,
            "running": total_runs - completed_runs - failed_runs,
            "success_rate": round(
                completed_runs / max(total_runs, 1) * 100, 1
            ),
        },
        "cost": {
            "total_cents": total_cost,
            "avg_per_run_cents": round(total_cost / max(total_runs, 1)),
        },
        "governance": {
            "violations": total_violations,
            "freeze_events": total_freezes,
            "council_votes": total_council_votes,
        },
        "intelligence": {
            "signals_captured": total_signals,
            "evidence_artifacts": total_evidence,
        },
        "timestamp": datetime.utcnow().isoformat(),
    }


# ---------------------------------------------------------------------------
# Guardrails reference
# ---------------------------------------------------------------------------


@router.get("/guardrails")
async def list_guardrails(admin_email: str = Depends(require_admin)):
    """Return the full guardrail ruleset."""
    return {
        "categories": [
            {
                "id": "CQ",
                "name": "Code Quality",
                "rules": [
                    {"id": "CQ-01", "rule": "All code must pass linting before PR", "severity": "CRITICAL"},
                    {"id": "CQ-02", "rule": "All code must include type hints", "severity": "HIGH"},
                    {"id": "CQ-03", "rule": "No Any types, getattr, setattr", "severity": "HIGH"},
                    {"id": "CQ-04", "rule": "All endpoints must have Pydantic schemas", "severity": "HIGH"},
                    {"id": "CQ-05", "rule": "Test coverage must not decrease", "severity": "MEDIUM"},
                    {"id": "CQ-06", "rule": "No TODO/FIXME without linked issue", "severity": "LOW"},
                    {"id": "CQ-07", "rule": "Database migrations must be reversible", "severity": "HIGH"},
                    {"id": "CQ-08", "rule": "No hardcoded secrets in code", "severity": "CRITICAL"},
                    {"id": "CQ-09", "rule": "All imports at top of file", "severity": "MEDIUM"},
                    {"id": "CQ-10", "rule": "Follow existing code conventions", "severity": "MEDIUM"},
                ],
            },
            {
                "id": "SEC",
                "name": "Security",
                "rules": [
                    {"id": "SEC-01", "rule": "No secrets in logs or API responses", "severity": "CRITICAL"},
                    {"id": "SEC-02", "rule": "All user input validated via Pydantic", "severity": "CRITICAL"},
                    {"id": "SEC-03", "rule": "All endpoints must have authentication", "severity": "CRITICAL"},
                    {"id": "SEC-04", "rule": "Rate limiting on all public endpoints", "severity": "HIGH"},
                    {"id": "SEC-05", "rule": "No SQL injection vectors", "severity": "CRITICAL"},
                    {"id": "SEC-06", "rule": "No CORS wildcard in production", "severity": "HIGH"},
                    {"id": "SEC-07", "rule": "No known CVEs above CVSS 7.0", "severity": "HIGH"},
                    {"id": "SEC-08", "rule": "JWT RS256 with proper expiry", "severity": "HIGH"},
                    {"id": "SEC-09", "rule": "PII encrypted at rest (AES-256)", "severity": "HIGH"},
                    {"id": "SEC-10", "rule": "All security ops produce audit logs", "severity": "MEDIUM"},
                ],
            },
            {
                "id": "OPS",
                "name": "Operational",
                "rules": [
                    {"id": "OPS-01", "rule": "Never push directly to main/master", "severity": "CRITICAL"},
                    {"id": "OPS-02", "rule": "Never force push to shared branches", "severity": "CRITICAL"},
                    {"id": "OPS-03", "rule": "Never modify another agent's files without coordination", "severity": "HIGH"},
                    {"id": "OPS-04", "rule": "Never skip pre-commit hooks", "severity": "HIGH"},
                    {"id": "OPS-05", "rule": "All PRs must have descriptions", "severity": "MEDIUM"},
                    {"id": "OPS-06", "rule": "Update PROGRESS.md after completing tasks", "severity": "MEDIUM"},
                    {"id": "OPS-07", "rule": "Report blockers within 1 hour", "severity": "HIGH"},
                    {"id": "OPS-08", "rule": "Never delete another agent's work without approval", "severity": "CRITICAL"},
                    {"id": "OPS-09", "rule": "Respond to Zeno Interrogation within 30 seconds", "severity": "MEDIUM"},
                    {"id": "OPS-10", "rule": "Crawler agents must respect robots.txt", "severity": "HIGH"},
                ],
            },
            {
                "id": "DS",
                "name": "Data Sovereignty",
                "rules": [
                    {"id": "DS-01", "rule": "User data must never leave designated hosting region", "severity": "CRITICAL"},
                    {"id": "DS-02", "rule": "No third-party analytics that transmit PII externally", "severity": "HIGH"},
                    {"id": "DS-03", "rule": "All data exports approved by Agent-105", "severity": "HIGH"},
                    {"id": "DS-04", "rule": "Vector embeddings must stay on sovereign infrastructure", "severity": "HIGH"},
                    {"id": "DS-05", "rule": "Agent memory must not persist PII beyond session", "severity": "HIGH"},
                ],
            },
            {
                "id": "COL",
                "name": "Collaboration",
                "rules": [
                    {"id": "COL-01", "rule": "No completion claims without verifiable evidence", "severity": "HIGH"},
                    {"id": "COL-02", "rule": "Dependency requests acknowledged within 2 hours", "severity": "MEDIUM"},
                    {"id": "COL-03", "rule": "Cross-committee decisions require delegate approval", "severity": "HIGH"},
                    {"id": "COL-04", "rule": "Commander directives override all other priorities", "severity": "CRITICAL"},
                    {"id": "COL-05", "rule": "Research agents must provide citations", "severity": "MEDIUM"},
                    {"id": "COL-06", "rule": "Browser agents must capture screenshots as evidence", "severity": "MEDIUM"},
                    {"id": "COL-07", "rule": "Vendor hunters must not spam or harass", "severity": "CRITICAL"},
                    {"id": "COL-08", "rule": "All handoffs must include context transfer docs", "severity": "MEDIUM"},
                ],
            },
        ],
        "penalty_levels": [
            {"level": 1, "name": "Advisory", "action": "Warning logged"},
            {"level": 2, "name": "Corrective Action", "action": "Task reassigned, retraining"},
            {"level": 3, "name": "Priority Demotion", "action": "Rank reduced, voting weight cut"},
            {"level": 4, "name": "Suspension", "action": "Agent frozen, resources stripped"},
            {"level": 5, "name": "Retirement", "action": "Agent permanently decommissioned"},
        ],
        "agent_ranks": ["Recruit", "Operative", "Specialist", "Elite", "Commander"],
        "timestamp": datetime.utcnow().isoformat(),
    }


# ---------------------------------------------------------------------------
# Seed — populate agent definitions from /agents/ mission files
# ---------------------------------------------------------------------------

_DIR_TO_GROUP = {
    "phase0-scaffolding": "Scaffolding",
    "phase1-engineering": "Core Engineers",
    "phase2-vendor-acquisition": "Vendor Acquisition",
    "phase3-user-acquisition": "User Acquisition",
    "phase4-retention-revenue": "Retention & Revenue",
    "phase5-daily-operations": "Daily Operations",
    "rag-knowledge": "RAG Knowledge",
    "security-force": "Security Force",
    "eyes-visual": "Visual Agents",
    "hrm-workforce": "HRM Workforce",
    "special-governance": "Research / Special Ops",
}

_CONTROL_AGENTS = {0, 108, 109, 110, 111, 112, 113}
_SPECIAL_GOV_RANGE = range(120, 130)

import re as _re
from pathlib import Path as _Path


def _parse_agent_files() -> list[dict]:
    agents_dir = _Path(__file__).resolve().parents[3] / "agents"
    if not agents_dir.exists():
        return []
    results: list[dict] = []
    for dirn in sorted(agents_dir.iterdir()):
        if not dirn.is_dir():
            continue
        group = _DIR_TO_GROUP.get(dirn.name, "General")
        for fpath in sorted(dirn.glob("agent-*.md")):
            m = _re.match(r"agent-(\d+)-(.+)\.md", fpath.name)
            if not m:
                continue
            num = int(m.group(1))
            codename_slug = m.group(2)
            lines = fpath.read_text(errors="replace").splitlines()
            title = codename_slug.replace("-", " ").title()
            mission = "Operational agent"
            phase = dirn.name
            committee = group
            priority = "MEDIUM"
            capabilities: list[str] = []

            for line in lines:
                if line.startswith("# Agent-") and " — " in line:
                    title = line.split(" — ", 1)[1].strip()
                if line.startswith("**Committee:**"):
                    committee = line.split(":**", 1)[1].strip()
                if line.startswith("**Phase:**"):
                    phase = line.split(":**", 1)[1].strip().split(" — ")[0].strip()
                if line.startswith("**Priority:**"):
                    priority = line.split(":**", 1)[1].strip().split(" — ")[0].strip()

            in_mission = False
            for line in lines:
                if line.strip().startswith("## Mission"):
                    in_mission = True
                    continue
                if in_mission:
                    if line.strip().startswith("##"):
                        break
                    if line.strip():
                        mission = line.strip()[:500]
                        break

            if "eyes" in codename_slug or "visual" in codename_slug:
                capabilities.append("eyes")
            if "hrm" in codename_slug:
                capabilities.append("hrm")
            if "rag" in codename_slug:
                capabilities.append("rag")
            if "security" in codename_slug or "sentinel" in codename_slug:
                capabilities.append("sentinel")
            if "zeno" in codename_slug:
                capabilities.append("zeno")
            if "gladiator" in codename_slug:
                capabilities.append("gladiator")
            if "listener" in codename_slug:
                capabilities.append("listener")
            if "scientist" in codename_slug or "ssrn" in codename_slug or "arxiv" in codename_slug:
                capabilities.append("scientist")

            is_control = num in _CONTROL_AGENTS
            is_special = num in _SPECIAL_GOV_RANGE

            results.append({
                "agent_number": num,
                "name": title,
                "codename": codename_slug,
                "group": group,
                "phase": phase,
                "committee": committee,
                "priority": priority,
                "mission": mission,
                "capabilities": capabilities,
                "is_control_agent": is_control,
                "rank_level": 90 if is_special else (80 if is_control else 50),
                "voting_weight": 3.0 if is_special else (2.0 if is_control else 1.0),
            })
    return results


@router.post("/seed")
async def seed_agents(
    admin_email: str = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Populate agent_definitions from /agents/ mission files.

    Idempotent — skips agents whose agent_number already exists.
    """
    parsed = _parse_agent_files()
    if not parsed:
        raise HTTPException(status_code=404, detail="No agent mission files found in /agents/")

    existing_q = await db.execute(select(AgentDefinition.agent_number))
    existing_nums = {row[0] for row in existing_q.fetchall()}

    created = 0
    for a in parsed:
        if a["agent_number"] in existing_nums:
            continue
        defn = AgentDefinition(
            agent_number=a["agent_number"],
            name=a["name"],
            codename=a["codename"],
            group=a["group"],
            phase=a["phase"],
            committee=a["committee"],
            priority=a["priority"],
            mission=a["mission"],
            capabilities=a["capabilities"],
            is_control_agent=a["is_control_agent"],
            rank_level=a["rank_level"],
            voting_weight=a["voting_weight"],
        )
        db.add(defn)
        created += 1

    await db.commit()
    return {
        "seeded": created,
        "skipped": len(parsed) - created,
        "total_parsed": len(parsed),
        "agent_count_model": {
            "operational": 114,
            "control_council": 6,
            "special_governance": 10,
            "total": 130,
        },
        "timestamp": datetime.utcnow().isoformat(),
    }
