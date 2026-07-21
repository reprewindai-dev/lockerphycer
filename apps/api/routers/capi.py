from typing import Any, Dict

from fastapi import APIRouter, Header, HTTPException, status
from pydantic import BaseModel

router = APIRouter(prefix="/capi", tags=["cAPI Interlink"])

class ExecutionRequest(BaseModel):
    action: str
    payload: Dict[str, Any]

@router.post("/v1/execute")
async def capi_execute(
    request: ExecutionRequest,
    x_agent_id: str = Header(..., description="Veklom Agent ID"),
    authorization: str = Header(..., description="Bearer JWT for PGL identity"),
):
    """
    Dedicated cAPI intercept. Ensures PGL identity constraints are applied
    before allowing autonomous execution against Lockersphere primitives.
    """
    
    if not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing or invalid Bearer token")
        
    raise HTTPException(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        detail={
            "status": "BLOCKED",
            "reason": "CAPPO execution authority is not connected; no action was executed.",
            "action": request.action,
        },
    )
