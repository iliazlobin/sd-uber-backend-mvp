"""FastAPI application factory with lifespan and health check."""

from collections.abc import Awaitable, Callable
from contextlib import asynccontextmanager, suppress

from fastapi import FastAPI

from .database import _get_engine, _request_session
from .redis_client import _get_client, close_redis
from .routers import drivers, health, riders, rides


# -- ASGI middleware: commit DB session BEFORE response headers --

class DBSessionMiddleware:
    """Commit the per-request DB session before the first response byte.

    FastAPI's dependency-generator cleanup runs *after* the ASGI response
    is sent, creating a race where a client can receive a 201 and fire a
    follow-up request before the ``session.commit()`` completes.  This
    middleware hooks the ASGI ``send`` to commit *before* the
    ``http.response.start`` event, making the data durable by the time the
    client sees the response.
    """

    def __init__(self, app: Callable) -> None:
        self.app = app

    async def __call__(self, scope, receive, send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        async def _send(message):
            if message["type"] == "http.response.start":
                session = _request_session.get()
                if session is not None and session.is_active:
                    await session.commit()
            await send(message)

        await self.app(scope, receive, _send)


# -- Lifespan & app factory --


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Trigger lazy engine creation on startup
    _get_engine()
    # Redis is best-effort at scaffold stage — missing Redis does not block app start
    with suppress(Exception):
        await _get_client()
    yield
    # Cleanup on shutdown
    engine, _ = _get_engine()
    await engine.dispose()
    with suppress(Exception):
        await close_redis()


def create_app() -> FastAPI:
    app = FastAPI(lifespan=lifespan)

    app.include_router(health.router)
    app.include_router(riders.router)
    app.include_router(drivers.router)
    app.include_router(rides.router)

    # Register the commit-before-response middleware.
    # It wraps the entire app so every request gets automatic commit.
    app.add_middleware(DBSessionMiddleware)

    return app


# Module-level ASGI app for `uvicorn uber.main:app` (no --factory needed).
# Safe at import: create_app() only builds the app + routers; DB/Redis work
# happens per-request / in the lifespan handler, not here.
app = create_app()
