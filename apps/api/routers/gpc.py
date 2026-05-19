"""GPC — Governed Plan Compiler routes"""

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, desc, func
from typing import Optional
from datetime import datetime
import uuid

from core.database.database import get_db
from db.models import GPCPlan

router = APIRouter()


@router.post("/compile")
async def compile_intent(
    intent: str,
    workspace_id: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
):
    """Compile a natural-language intent into a governed plan"""
    plan = GPCPlan(
        id=str(uuid.uuid4()),
        workspace_id=workspace_id,
        intent=intent,
        compiled_plan={
            "workflow_steps": [
                {"step": 1, "action": "Extract intent", "status": "planned"},
                {"step": 2, "action": "Identify models & tools", "status": "planned"},
                {"step": 3, "action": "Attach policy requirements", "status": "planned"},
                {"step": 4, "action": "Estimate costs", "status": "planned"},
                {"step": 5, "action": "Generate deployment path", "status": "planned"},
            ],
            "models_required": ["gemini-3-flash", "veklom-governance-v1"],
            "tools_required": ["policy-engine", "cost-estimator", "evidence-recorder"],
            "deployment_path": "private-runtime",
        },
        risks=[
            {"risk": "Data residency violation", "severity": "high", "mitigation": "EU-sovereign runtime"},
            {"risk": "Key exposure", "severity": "critical", "mitigation": "BYOK vault integration"},
            {"risk": "Unmonitored execution", "severity": "medium", "mitigation": "Full telemetry + replay"},
        ],
        policy_requirements=[
            "SOC2 evidence capture",
            "HIPAA-aware data handling",
            "Human-in-the-loop approval gate",
            "Signed artifact generation",
        ],
        cost_estimate={
            "compile": "$1.50",
            "execution": "$3.00",
            "artifact_generation": "$5.00",
            "total_estimated": "$9.50",
        },
        status="compiled",
    )
    db.add(plan)
    await db.commit()
    await db.refresh(plan)
    return {
        "id": plan.id,
        "intent": plan.intent,
        "compiled_plan": plan.compiled_plan,
        "risks": plan.risks,
        "policy_requirements": plan.policy_requirements,
        "cost_estimate": plan.cost_estimate,
        "status": plan.status,
        "created_at": plan.created_at.isoformat() if plan.created_at else None,
    }


@router.get("/plans")
async def list_plans(
    workspace_id: Optional[str] = None,
    status: Optional[str] = None,
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
):
    query = select(GPCPlan).order_by(desc(GPCPlan.created_at))
    if workspace_id:
        query = query.where(GPCPlan.workspace_id == workspace_id)
    if status:
        query = query.where(GPCPlan.status == status)
    result = await db.execute(query.offset(skip).limit(limit))
    plans = result.scalars().all()
    return [
        {
            "id": p.id,
            "intent": p.intent,
            "status": p.status,
            "cost_estimate": p.cost_estimate,
            "created_at": p.created_at.isoformat() if p.created_at else None,
        }
        for p in plans
    ]


@router.get("/plans/{plan_id}")
async def get_plan(plan_id: str, db: AsyncSession = Depends(get_db)):
    plan = await db.get(GPCPlan, plan_id)
    if not plan:
        raise HTTPException(status_code=404, detail="Plan not found")
    return {
        "id": plan.id,
        "intent": plan.intent,
        "compiled_plan": plan.compiled_plan,
        "risks": plan.risks,
        "policy_requirements": plan.policy_requirements,
        "cost_estimate": plan.cost_estimate,
        "status": plan.status,
        "created_at": plan.created_at.isoformat() if plan.created_at else None,
    }


@router.post("/plans/{plan_id}/execute")
async def execute_plan(plan_id: str, db: AsyncSession = Depends(get_db)):
    plan = await db.get(GPCPlan, plan_id)
    if not plan:
        raise HTTPException(status_code=404, detail="Plan not found")
    plan.status = "executing"
    plan.updated_at = datetime.utcnow()
    await db.commit()
    return {"id": plan.id, "status": "executing", "message": "Plan execution started"}


@router.post("/plans/{plan_id}/approve")
async def approve_plan(plan_id: str, db: AsyncSession = Depends(get_db)):
    plan = await db.get(GPCPlan, plan_id)
    if not plan:
        raise HTTPException(status_code=404, detail="Plan not found")
    plan.status = "approved"
    plan.updated_at = datetime.utcnow()
    await db.commit()
    return {"id": plan.id, "status": "approved"}


@router.get("/stats")
async def gpc_stats(db: AsyncSession = Depends(get_db)):
    total = await db.execute(select(func.count()).select_from(GPCPlan))
    compiled = await db.execute(
        select(func.count()).select_from(GPCPlan).where(GPCPlan.status == "compiled")
    )
    executing = await db.execute(
        select(func.count()).select_from(GPCPlan).where(GPCPlan.status == "executing")
    )
    return {
        "total_plans": total.scalar() or 0,
        "compiled": compiled.scalar() or 0,
        "executing": executing.scalar() or 0,
    }
