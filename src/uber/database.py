"""Database engine, session factory, and FastAPI dependency."""

import contextvars
import os
from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from .config import settings

_engine = None
_async_session = None

# Per-request session context for middleware-driven commit-before-response.
_request_session: contextvars.ContextVar[AsyncSession | None] = contextvars.ContextVar(
    "request_session", default=None
)


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
    """Yield a per-request AsyncSession.

    The session is NOT committed in this dependency generator — that is
    handled by ``DBSessionMiddleware``, which commits **before** the HTTP
    response headers are sent, eliminating the async race where a follow-up
    request could arrive before the commit completed.
    """
    engine, maker = _get_engine()
    async with maker() as session:
        token = _request_session.set(session)
        try:
            yield session
        except Exception:
            await session.rollback()
            raise
        finally:
            _request_session.reset(token)
