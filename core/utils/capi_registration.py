import asyncio
import logging
from typing import Any

import httpx

from core.config.settings import Settings

logger = logging.getLogger(__name__)


def build_registration_payload() -> dict[str, Any]:
    """Build endpoint-backed capabilities for cAPI discovery."""
    return {
        "service_name": "lockerphycer",
        "base_url": "https://command.veklom.com",
        "telemetry_supported": True,
        "capabilities": [
            {
                "name": "authenticate_users",
                "description": "Authenticate a Lockerphycer user and issue session tokens.",
                "endpoint": "https://command.veklom.com/api/v1/auth/login",
                "input_schema": {
                    "type": "object",
                    "required": ["email", "password"],
                    "properties": {
                        "email": {"type": "string", "format": "email"},
                        "password": {"type": "string", "format": "password"},
                    },
                },
                "risk_level": "high",
                "requires_approval": False,
            },
            {
                "name": "retrieve_current_identity",
                "description": "Retrieve the authenticated user's Lockerphycer identity.",
                "endpoint": "https://command.veklom.com/api/v1/auth/me",
                "input_schema": {"type": "object", "properties": {}},
                "risk_level": "low",
                "requires_approval": False,
            },
            {
                "name": "register_users",
                "description": "Create a Lockerphycer user identity.",
                "endpoint": "https://command.veklom.com/api/v1/auth/register",
                "input_schema": {
                    "type": "object",
                    "required": ["email", "username", "full_name", "password"],
                    "properties": {
                        "email": {"type": "string", "format": "email"},
                        "username": {"type": "string"},
                        "full_name": {"type": "string"},
                        "password": {"type": "string", "format": "password"},
                    },
                },
                "risk_level": "high",
                "requires_approval": True,
            },
            {
                "name": "inspect_agent_identity",
                "description": "Read an agent definition from the Lockerphycer registry.",
                "endpoint": "https://command.veklom.com/api/v1/agents/registry/{agent_number}",
                "input_schema": {
                    "type": "object",
                    "required": ["agent_number"],
                    "properties": {"agent_number": {"type": "integer"}},
                },
                "risk_level": "low",
                "requires_approval": False,
            },
        ],
        "metadata": {
            "protocol": "veklom-service-registration-v1",
            "manifest": "https://command.veklom.com/protocol.json",
        },
    }


async def register_with_capi(settings: Settings) -> None:
    """Registers Lockerphycer capabilities with the cAPI Universal USB layer."""
    if not settings.CAPI_BACKEND_URL:
        logger.info("[cAPI] Registration skipped: CAPI_BACKEND_URL is not set.")
        return
        
    url = f"{settings.CAPI_BACKEND_URL.rstrip('/')}/api/v1/registry/register"
    headers = {"Content-Type": "application/json"}
    if settings.CAPI_API_KEY:
        headers["Authorization"] = f"Bearer {settings.CAPI_API_KEY}"
        
    payload = build_registration_payload()
    
    import socket
    from urllib.parse import urlparse
    
    # DNS Fallback logic for gaierror Name resolution
    parsed = urlparse(url)
    try:
        # Try to resolve the hostname explicitly to catch DNS errors early
        socket.gethostbyname(parsed.hostname)
    except socket.gaierror:
        logger.warning(f"[cAPI] DNS resolution failed for {parsed.hostname}. Falling back to internal Docker network (capi-container).")
        # Swap hostname for 'capi-container' (default Coolify internal name)
        url = url.replace(parsed.hostname, "capi-container")

    for attempt in range(5):
        try:
            async with httpx.AsyncClient() as client:
                response = await client.post(url, json=payload, headers=headers, timeout=5.0)
                if response.status_code in (200, 201):
                    logger.info("[cAPI] Successfully registered Lockerphycer with cAPI.")
                    return
                else:
                    logger.warning(f"[cAPI] Failed to register: {response.text}")
        except Exception as exc:  # noqa: BLE001 - registration must remain fail-soft
            logger.warning(
                "[cAPI] Registration attempt %s failed (%s)",
                attempt + 1,
                type(exc).__name__,
            )

        if attempt < 4:
            await asyncio.sleep(5)
