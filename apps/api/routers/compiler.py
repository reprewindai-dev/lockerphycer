import hashlib
import json
from typing import Any, Dict, List, Optional
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

router = APIRouter()

# ── Pydantic Schemas for Deterministic Compilation (Layer 4) ──────────────────

class RepositoryConstraint(BaseModel):
    allowed_paths: List[str] = Field(default_factory=lambda: ["**/*"])
    forbidden_paths: List[str] = Field(default_factory=list)

class CanonicalBlueprintV1(BaseModel):
    id: str
    schema_version: str = "1.0.0"
    intent: str
    requirements: List[str]
    constraints: RepositoryConstraint
    metadata: Optional[Dict[str, Any]] = None

class PlanStepV1(BaseModel):
    id: str
    action: str
    description: str
    capability: Optional[str] = None
    dependencies: List[str] = Field(default_factory=list)

class PlanIRV1(BaseModel):
    id: str
    blueprint_hash: str
    schema_version: str = "1.0.0"
    steps: List[PlanStepV1]

class CompileRequest(BaseModel):
    intent: str
    requirements: List[str] = Field(default_factory=list)
    forbidden_paths: List[str] = Field(default_factory=list)

# ── Hashing Utility (RFC-8785 style canonical JSON) ───────────────────────────

def compute_canonical_hash(obj: BaseModel) -> str:
    """
    Computes a deterministic SHA-256 hash by dumping the model to a 
    strictly sorted JSON string (simulating RFC-8785 canonicalization).
    """
    # model_dump_json(exclude_unset=True, exclude_none=True) + sorted_keys
    # Note: For true RFC-8785 we'd use a dedicated canonicalizer, but sorted_keys
    # combined with Pydantic strict typing ensures mathematical consistency.
    json_str = obj.model_dump_json(exclude_none=True, by_alias=True)
    parsed = json.loads(json_str)
    canonical_str = json.dumps(parsed, separators=(',', ':'), sort_keys=True)
    return "sha256:" + hashlib.sha256(canonical_str.encode("utf-8")).hexdigest()

# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.post("/compile")
async def compile_intent(request: CompileRequest):
    """
    SEKED Compiler Endpoint (Layer 4)
    Compiles an unstructured natural language intent into a strictly-typed,
    deterministically hashed Intermediate Representation (PlanIR).
    """
    # In a full implementation, this uses the SEKED 100,000-state matrix 
    # to deterministically resolve the intent. We simulate the deterministic 
    # resolution here by directly mapping inputs to the strictly typed schema.
    
    blueprint_id = f"bp_{hashlib.sha256(request.intent.encode()).hexdigest()[:8]}"
    
    blueprint = CanonicalBlueprintV1(
        id=blueprint_id,
        intent=request.intent,
        requirements=request.requirements,
        constraints=RepositoryConstraint(
            forbidden_paths=request.forbidden_paths
        )
    )
    
    blueprint_hash = compute_canonical_hash(blueprint)
    
    # Generate the discrete steps (simulating the SEKED matrix output)
    plan = PlanIRV1(
        id=f"plan_{blueprint_id}",
        blueprint_hash=blueprint_hash,
        steps=[
            PlanStepV1(
                id=f"step_1",
                action="Execute Intent",
                description="Mathematically bounded execution of the requested intent.",
                capability="repo.apply_patch"
            )
        ]
    )
    
    plan_hash = compute_canonical_hash(plan)
    
    return {
        "status": "COMPILED",
        "blueprint_hash": blueprint_hash,
        "plan_hash": plan_hash,
        "plan": plan.model_dump()
    }
