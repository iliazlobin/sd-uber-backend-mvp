"""Async Redis client and FastAPI dependency."""

import os
from collections.abc import AsyncGenerator

import redis.asyncio as aioredis

from .config import settings

_client: aioredis.Redis | None = None


async def _get_client() -> aioredis.Redis:
    global _client
    if _client is None:
        url = os.getenv("REDIS_URL", settings.redis_url)
        _client = aioredis.from_url(url, decode_responses=True)
    return _client


async def get_redis() -> AsyncGenerator[aioredis.Redis, None]:
    client = await _get_client()
    yield client


async def close_redis() -> None:
    global _client
    if _client is not None:
        await _client.close()
        _client = None
