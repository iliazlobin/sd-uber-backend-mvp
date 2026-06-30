"""Test fixtures for white-box unit tests."""

import os

import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from uber.database import get_session
from uber.main import create_app
from uber.redis_client import get_redis

TEST_DB_URL = os.environ.get(
    "DATABASE_URL",
    "postgresql+asyncpg://postgres:postgres@localhost:5432/uber",
)

TEST_REDIS_URL = os.environ.get(
    "REDIS_URL",
    "redis://localhost:6379/0",
)


@pytest_asyncio.fixture(scope="function")
async def test_engine():
    """Create a fresh async engine per test function to avoid event-loop issues."""
    engine = create_async_engine(TEST_DB_URL)
    yield engine
    await engine.dispose()


@pytest_asyncio.fixture(scope="function")
async def sessionmaker(test_engine):
    """Create a sessionmaker bound to the test engine."""
    return async_sessionmaker(test_engine, class_=AsyncSession, expire_on_commit=False)


@pytest_asyncio.fixture
async def session(sessionmaker):
    """Create a transaction-rollback session per test."""
    async with sessionmaker() as session, session.begin():
        yield session
        await session.rollback()


@pytest_asyncio.fixture
async def client(session):
    """Create an ASGI test client with test session and redis injected."""

    async def override_get_session():
        yield session

    import redis.asyncio as aioredis

    redis_client = aioredis.from_url(TEST_REDIS_URL, decode_responses=True)

    async def override_get_redis():
        yield redis_client

    app = create_app()
    app.dependency_overrides[get_session] = override_get_session
    app.dependency_overrides[get_redis] = override_get_redis

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        yield ac

    try:
        await redis_client.aclose()
    except Exception:
        await redis_client.close()
