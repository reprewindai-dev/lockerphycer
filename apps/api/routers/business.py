"""Revenue control-plane endpoints: BYOK cost, compliance mappings, managed services."""

from __future__ import annotations

import csv
import io
from datetime import datetime, timedelta
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import and_, desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from core.database.database import get_db
from core.security.auth import require_admin
from db.models import AIProviderUsage, ComplianceMapping, ManagedServiceQuote, Workspace

router = APIRouter()


class ProviderUsageCreate(BaseModel):
    workspace_id: str
    provider: str = Field(..., min_length=2, max_length=80)
    model: str = Field(..., min_length=1, max_length=120)
    route_type: str = Field("byok", pattern="^(byok|managed|local|cache)$")
    prompt_tokens: int = Field(0, ge=0)
    completion_tokens: int = Field(0, ge=0)
    request_count: int = Field(1, ge=1)
    provider_cost_cents: int = Field(0, ge=0)
    baseline_cost_cents: int = Field(0, ge=0)
    cache_hit: bool = False
    cache_savings_cents: int = Field(0, ge=0)
    local_route_savings_cents: int = Field(0, ge=0)


class ComplianceMappingCreate(BaseModel):
    framework: str = Field(..., min_length=2, max_length=80)
    control_id: str = Field(..., min_length=1, max_length=80)
    control_title: str = Field(..., min_length=3, max_length=240)
    lockerphycer_configuration: str = Field(..., min_length=3)
    evidence_source: str = Field(..., min_length=2, max_length=160)
    evidence_route: Optional[str] = Field(None, max_length=240)
    owner_role: str = Field("security_admin", max_length=80)
    implementation_status: str = Field("configured", pattern="^(configured|verified|customer_action|not_applicable)$")
    export_notes: Optional[str] = None


class ManagedServiceQuoteRequest(BaseModel):
    workspace_id: Optional[str] = None
    environment_count: int = Field(1, ge=1, le=25)
    node_count: int = Field(3, ge=1, le=1000)
    cluster_count: int = Field(1, ge=1, le=100)
    regulated_workload: bool = False
    air_gapped: bool = False


DEFAULT_COMPLIANCE_MAPPINGS = [
    {
        "framework": "SOC2",
        "control_id": "CC6.1",
        "control_title": "Logical access controls",
        "lockerphycer_configuration": "JWT authentication, role-based authorization, admin route guard, and session revocation.",
        "evidence_source": "Auth configuration and user session records",
        "evidence_route": "/api/v1/auth/me, /api/v1/command-center/sessions",
        "implementation_status": "configured",
        "export_notes": "Attach user access review export and admin route inventory.",
    },
    {
        "framework": "SOC2",
        "control_id": "CC7.2",
        "control_title": "Security event monitoring",
        "lockerphycer_configuration": "SecurityEvent records capture severity, threat type, assignment, AI analysis, and resolution state.",
        "evidence_source": "Security event ledger",
        "evidence_route": "/api/v1/security/events",
        "implementation_status": "verified",
        "export_notes": "Filter by audit period and include resolved_at evidence.",
    },
    {
        "framework": "HIPAA",
        "control_id": "164.312(b)",
        "control_title": "Audit controls",
        "lockerphycer_configuration": "AuditLog and EvidenceArtifact tables preserve administrative and governed execution evidence.",
        "evidence_source": "Audit log and evidence artifacts",
        "evidence_route": "/api/v1/command-center/audit-log, /api/v1/agents/evidence",
        "implementation_status": "verified",
        "export_notes": "Use customer deployment logs to prove retention and backup policy.",
    },
    {
        "framework": "GDPR",
        "control_id": "Art. 32",
        "control_title": "Security of processing",
        "lockerphycer_configuration": "BYOS deployment keeps telemetry and AI prompts inside customer-controlled infrastructure.",
        "evidence_source": "Workspace deployment configuration",
        "evidence_route": "/api/v1/workspace/{workspace_id}",
        "implementation_status": "configured",
        "export_notes": "Attach cloud region, network boundary, and DPA/TIA artifacts.",
    },
    {
        "framework": "PIPEDA",
        "control_id": "Principle 4.7",
        "control_title": "Safeguards",
        "lockerphycer_configuration": "RBAC, audit logs, security events, and provider cost controls reduce unauthorized AI/data exposure.",
        "evidence_source": "Security controls and BYOK dashboard",
        "evidence_route": "/api/v1/security/controls, /api/v1/business/byok-cost/{workspace_id}",
        "implementation_status": "configured",
        "export_notes": "Include customer policies for credential rotation and incident response.",
    },
]


@router.post("/byok-usage")
async def record_byok_usage(
    payload: ProviderUsageCreate,
    admin_email: str = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    workspace = await db.get(Workspace, payload.workspace_id)
    if not workspace:
        raise HTTPException(status_code=404, detail="Workspace not found")

    usage = AIProviderUsage(**payload.model_dump())
    db.add(usage)
    await db.commit()
    await db.refresh(usage)
    return {"id": usage.id, "workspace_id": usage.workspace_id, "recorded": True}


@router.get("/byok-cost/{workspace_id}")
async def byok_cost_dashboard(
    workspace_id: str,
    days: int = Query(30, ge=1, le=365),
    admin_email: str = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    since = datetime.utcnow() - timedelta(days=days)
    rows = (
        await db.execute(
            select(
                AIProviderUsage.provider,
                AIProviderUsage.model,
                AIProviderUsage.route_type,
                func.sum(AIProviderUsage.request_count),
                func.sum(AIProviderUsage.prompt_tokens + AIProviderUsage.completion_tokens),
                func.sum(AIProviderUsage.provider_cost_cents),
                func.sum(AIProviderUsage.baseline_cost_cents),
                func.sum(AIProviderUsage.cache_savings_cents),
                func.sum(AIProviderUsage.local_route_savings_cents),
            )
            .where(and_(AIProviderUsage.workspace_id == workspace_id, AIProviderUsage.created_at >= since))
            .group_by(AIProviderUsage.provider, AIProviderUsage.model, AIProviderUsage.route_type)
            .order_by(desc(func.sum(AIProviderUsage.provider_cost_cents)))
        )
    ).all()

    providers = []
    totals = {
        "requests": 0,
        "tokens": 0,
        "provider_cost_cents": 0,
        "baseline_cost_cents": 0,
        "cache_savings_cents": 0,
        "local_route_savings_cents": 0,
    }
    for provider, model, route_type, requests, tokens, provider_cost, baseline, cache_savings, local_savings in rows:
        item = {
            "provider": provider,
            "model": model,
            "route_type": route_type,
            "requests": requests or 0,
            "tokens": tokens or 0,
            "provider_cost_cents": provider_cost or 0,
            "baseline_cost_cents": baseline or 0,
            "cache_savings_cents": cache_savings or 0,
            "local_route_savings_cents": local_savings or 0,
        }
        item["total_savings_cents"] = max(
            item["baseline_cost_cents"] - item["provider_cost_cents"],
            item["cache_savings_cents"] + item["local_route_savings_cents"],
        )
        providers.append(item)
        for key in totals:
            totals[key] += item[key]

    totals["total_savings_cents"] = sum(p["total_savings_cents"] for p in providers)
    totals["savings_rate_pct"] = round(
        totals["total_savings_cents"] / max(totals["baseline_cost_cents"], 1) * 100,
        2,
    )
    return {
        "workspace_id": workspace_id,
        "period_days": days,
        "totals": totals,
        "providers": providers,
        "positioning": "BYOK cost visibility turns AI security governance into a measurable savings center.",
    }


@router.post("/compliance-mappings/seed")
async def seed_compliance_mappings(
    admin_email: str = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    existing = (await db.execute(select(func.count()).select_from(ComplianceMapping))).scalar() or 0
    if existing:
        return {"seeded": 0, "existing": existing}
    for mapping in DEFAULT_COMPLIANCE_MAPPINGS:
        db.add(ComplianceMapping(**mapping))
    await db.commit()
    return {"seeded": len(DEFAULT_COMPLIANCE_MAPPINGS), "existing": 0}


@router.post("/compliance-mappings")
async def create_compliance_mapping(
    payload: ComplianceMappingCreate,
    admin_email: str = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    mapping = ComplianceMapping(**payload.model_dump())
    db.add(mapping)
    await db.commit()
    await db.refresh(mapping)
    return {"id": mapping.id, "framework": mapping.framework, "control_id": mapping.control_id}


@router.get("/compliance-mappings")
async def list_compliance_mappings(
    framework: Optional[str] = None,
    status: Optional[str] = None,
    admin_email: str = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    query = select(ComplianceMapping).order_by(ComplianceMapping.framework, ComplianceMapping.control_id)
    if framework:
        query = query.where(ComplianceMapping.framework == framework)
    if status:
        query = query.where(ComplianceMapping.implementation_status == status)
    mappings = (await db.execute(query)).scalars().all()
    return {
        "mappings": [
            {
                "id": m.id,
                "framework": m.framework,
                "control_id": m.control_id,
                "control_title": m.control_title,
                "lockerphycer_configuration": m.lockerphycer_configuration,
                "evidence_source": m.evidence_source,
                "evidence_route": m.evidence_route,
                "owner_role": m.owner_role,
                "implementation_status": m.implementation_status,
                "export_notes": m.export_notes,
            }
            for m in mappings
        ],
        "total": len(mappings),
    }


@router.get("/compliance-mappings/export.csv")
async def export_compliance_mappings(
    framework: Optional[str] = None,
    admin_email: str = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    query = select(ComplianceMapping).order_by(ComplianceMapping.framework, ComplianceMapping.control_id)
    if framework:
        query = query.where(ComplianceMapping.framework == framework)
    mappings = (await db.execute(query)).scalars().all()

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow([
        "framework",
        "control_id",
        "control_title",
        "lockerphycer_configuration",
        "evidence_source",
        "evidence_route",
        "owner_role",
        "implementation_status",
        "export_notes",
    ])
    for m in mappings:
        writer.writerow([
            m.framework,
            m.control_id,
            m.control_title,
            m.lockerphycer_configuration,
            m.evidence_source,
            m.evidence_route or "",
            m.owner_role,
            m.implementation_status,
            m.export_notes or "",
        ])
    output.seek(0)
    filename = f"lockerphycer-{framework.lower()}-mapping.csv" if framework else "lockerphycer-compliance-mapping.csv"
    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


def calculate_managed_service_quote(req: ManagedServiceQuoteRequest) -> tuple[int, int, str, dict]:
    base = 150000
    environment_fee = max(req.environment_count - 1, 0) * 50000
    cluster_fee = req.cluster_count * 75000
    node_fee = req.node_count * 6500
    regulated_fee = 125000 if req.regulated_workload else 0
    air_gap_fee = 300000 if req.air_gapped else 0
    monthly = base + environment_fee + cluster_fee + node_fee + regulated_fee + air_gap_fee
    onboarding = 500000 + (req.cluster_count * 150000) + (250000 if req.air_gapped else 0)
    tier = "enterprise_mssp" if req.air_gapped or req.regulated_workload or req.node_count > 50 else "managed_ops"
    assumptions = {
        "base_monthly_cents": base,
        "per_environment_after_first_cents": 50000,
        "per_cluster_cents": 75000,
        "per_node_cents": 6500,
        "regulated_workload_cents": regulated_fee,
        "air_gapped_cents": air_gap_fee,
    }
    return monthly, onboarding, tier, assumptions


@router.post("/managed-service/quote")
async def quote_managed_service(
    req: ManagedServiceQuoteRequest,
    admin_email: str = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    if req.workspace_id and not await db.get(Workspace, req.workspace_id):
        raise HTTPException(status_code=404, detail="Workspace not found")

    monthly, onboarding, tier, assumptions = calculate_managed_service_quote(req)
    quote = ManagedServiceQuote(
        **req.model_dump(),
        monthly_fee_cents=monthly,
        onboarding_fee_cents=onboarding,
        support_tier=tier,
        assumptions=assumptions,
    )
    db.add(quote)
    await db.commit()
    await db.refresh(quote)
    return {
        "quote_id": quote.id,
        "monthly_fee_cents": monthly,
        "onboarding_fee_cents": onboarding,
        "support_tier": tier,
        "assumptions": assumptions,
    }


@router.get("/managed-service/pricing")
async def managed_service_pricing():
    return {
        "base_managed_ops_monthly_cents": 150000,
        "per_environment_after_first_cents": 50000,
        "per_cluster_cents": 75000,
        "per_node_cents": 6500,
        "regulated_workload_addon_cents": 125000,
        "air_gapped_addon_cents": 300000,
        "minimum_onboarding_cents": 500000,
        "positioning": "Managed service pricing scales with operational burden instead of underpricing enterprise Kubernetes support.",
    }
