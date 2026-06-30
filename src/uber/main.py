"""FastAPI application factory with lifespan and health check."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager, suppress

from fastapi import FastAPI

from .database import _get_engine
from .redis_client import _get_client, close_redis
from .routers import drivers, health, riders, rides


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
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

    return app


# Module-level ASGI app for `uvicorn uber.main:app` (no --factory needed).
# Safe at import: create_app() only builds the app + routers; DB/Redis work
# happens per-request / in the lifespan handler, not here.
app = create_app()
