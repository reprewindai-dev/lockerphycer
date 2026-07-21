import httpx
import logging
import asyncio
from core.config.settings import Settings

logger = logging.getLogger(__name__)

async def register_with_capi(settings: Settings) -> None:
    """Registers Lockerphycer capabilities with the cAPI Universal USB layer."""
    if not settings.CAPI_BACKEND_URL:
        logger.info("[cAPI] Registration skipped: CAPI_BACKEND_URL is not set.")
        return
        
    url = f"{settings.CAPI_BACKEND_URL.rstrip('/')}/api/v1/registry/register"
    headers = {"Content-Type": "application/json"}
    if settings.CAPI_API_KEY:
        headers["Authorization"] = f"Bearer {settings.CAPI_API_KEY}"
        
    payload = {
        "service_name": "lockerphycer",
        "capabilities": ["identity", "authentication", "sso"],
        "telemetry_supported": True
    }
    
    for attempt in range(5):
        try:
            async with httpx.AsyncClient() as client:
                response = await client.post(url, json=payload, headers=headers, timeout=5.0)
                if response.status_code in (200, 201):
                    logger.info("[cAPI] Successfully registered Lockerphycer with cAPI.")
                    return
                else:
                    logger.warning(f"[cAPI] Failed to register: {response.text}")
        except Exception as e:
            logger.error(f"[cAPI] Error registering with cAPI (attempt {attempt + 1}): {e}")
            
        await asyncio.sleep(5)
