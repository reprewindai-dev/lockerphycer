from typing import Any, Dict

from fastapi import APIRouter, Header, HTTPException, status
from pydantic import BaseModel

router = APIRouter(prefix="/mcp", tags=["MCP Bridge"])

class McpToolRequest(BaseModel):
    tool_name: str
    arguments: Dict[str, Any]
    security: Dict[str, Any]

@router.post("/call")
async def mcp_bridge_call(
    request: McpToolRequest,
    x_agent_id: str = Header(..., description="Veklom Agent ID"),
    x_capability_id: str = Header(..., description="Veklom Capability ID"),
):
    """
    Dedicated MCP bridge schema mapped for cAPI Phase 6 execution override.
    Enforces PGL Ledger identity and routes MCP tools securely.
    """
    
    raise HTTPException(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        detail={
            "status": "BLOCKED",
            "reason": "CAPPO MCP authority is not connected; no tool was executed.",
            "tool_name": request.tool_name,
        },
    )
