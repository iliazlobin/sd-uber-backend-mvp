"""Health check router — GET /healthz with DB probe."""

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from ..database import get_session
from ..schemas.health import HealthResponse

router = APIRouter(tags=["health"])


@router.get("/healthz", response_model=HealthResponse)
async def healthz(session: AsyncSession = Depends(get_session)):
    try:
        await session.execute(text("SELECT 1"))
        return HealthResponse(status="ok", db="connected")
    except Exception:
        return JSONResponse(
            status_code=503,
            content={"status": "unhealthy", "db": "disconnected"},
        )
