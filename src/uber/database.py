"""Database engine, session factory, and FastAPI dependency."""

import os
from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from .config import settings

_engine = None
_async_session = None


def _get_engine():
    global _engine, _async_session
    if _engine is None:
        url = os.getenv("DATABASE_URL", settings.database_url)
        _engine = create_async_engine(url)
        _async_session = async_sessionmaker(_engine, class_=AsyncSession, expire_on_commit=False)
    return _engine, _async_session


class Base(DeclarativeBase):
    pass


async def get_session() -> AsyncGenerator[AsyncSession, None]:
    engine, maker = _get_engine()
    async with maker() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
