"""
Redis Client Utilities
"""

import redis.asyncio as redis
from typing import Optional, Dict, Any
import json
import pickle

from core.config.settings import settings


class RedisClient:
    """Redis client wrapper"""
    
    def __init__(self):
        self.redis_url = settings.REDIS_URL
        self._client: Optional[redis.Redis] = None
    
    async def connect(self):
        """Connect to Redis"""
        if not self._client:
            self._client = redis.from_url(
                self.redis_url,
                encoding="utf-8",
                decode_responses=True
            )
        return self._client
    
    async def disconnect(self):
        """Disconnect from Redis"""
        if self._client:
            await self._client.close()
            self._client = None
    
    async def get(self, key: str) -> Optional[str]:
        """Get value from Redis"""
        client = await self.connect()
        return await client.get(key)
    
    async def set(self, key: str, value: str, expire: Optional[int] = None):
        """Set value in Redis"""
        client = await self.connect()
        await client.set(key, value, ex=expire)
    
    async def delete(self, key: str):
        """Delete key from Redis"""
        client = await self.connect()
        await client.delete(key)
    
    async def exists(self, key: str) -> bool:
        """Check if key exists"""
        client = await self.connect()
        return await client.exists(key)
    
    async def get_json(self, key: str) -> Optional[Dict[str, Any]]:
        """Get JSON value from Redis"""
        value = await self.get(key)
        if value:
            return json.loads(value)
        return None
    
    async def set_json(self, key: str, value: Dict[str, Any], expire: Optional[int] = None):
        """Set JSON value in Redis"""
        await self.set(key, json.dumps(value), expire)
    
    async def get_pickle(self, key: str) -> Optional[Any]:
        """Get pickled value from Redis"""
        value = await self.get(key)
        if value:
            return pickle.loads(value.encode('latin1'))
        return None
    
    async def set_pickle(self, key: str, value: Any, expire: Optional[int] = None):
        """Set pickled value in Redis"""
        pickled_value = pickle.dumps(value).decode('latin1')
        await self.set(key, pickled_value, expire)


# Global Redis client instance
redis_client = RedisClient()


async def get_redis_status() -> Dict[str, Any]:
    """Get Redis connection status"""
    try:
        client = await redis_client.connect()
        await client.ping()
        return {
            "status": "healthy",
            "message": "Redis connection successful"
        }
    except Exception as e:
        return {
            "status": "unhealthy",
            "message": str(e)
        }
