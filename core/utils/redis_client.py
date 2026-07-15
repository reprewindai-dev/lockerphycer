"""Redis health helpers."""


async def get_redis_status() -> dict:
    return {"status": "not_configured"}
