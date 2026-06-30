"""Driver router: POST /drivers, POST /drivers/{id}/location, GET /drivers/nearby."""

from fastapi import APIRouter, Depends, HTTPException, Query
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from ..database import get_session
from ..redis_client import get_redis
from ..schemas.driver import (
    DriverCreate,
    DriverLocationResponse,
    DriverLocationUpdate,
    DriverResponse,
    NearbyDriverResponse,
)
from ..services.driver_service import (
    create_driver,
    get_nearby_drivers,
    update_driver_location,
)

router = APIRouter(prefix="/drivers", tags=["drivers"])


@router.post("", status_code=201, response_model=DriverResponse)
async def create_driver_endpoint(
    body: DriverCreate,
    session: AsyncSession = Depends(get_session),
):
    """Create a new driver (OFFLINE by default)."""
    driver = await create_driver(session, body)
    return driver


@router.post("/{driver_id}/location", response_model=DriverLocationResponse)
async def update_location(
    driver_id: str,
    body: DriverLocationUpdate,
    session: AsyncSession = Depends(get_session),
    redis: Redis = Depends(get_redis),
):
    """Update driver GPS position and status."""
    from uuid import UUID as _UUID

    try:
        did = _UUID(driver_id)
    except ValueError:
        raise HTTPException(status_code=422, detail="Invalid driver_id format") from None

    try:
        driver = await update_driver_location(session, redis, did, body)
    except ValueError:
        raise HTTPException(status_code=404, detail="Driver not found") from None

    return driver


@router.get("/nearby", response_model=list[NearbyDriverResponse])
async def nearby_drivers(
    lat: float = Query(..., ge=-90, le=90),
    lng: float = Query(..., ge=-180, le=180),
    radius_km: float = Query(3.0, gt=0, le=50),
    session: AsyncSession = Depends(get_session),
    redis: Redis = Depends(get_redis),
):
    """List ONLINE drivers near a point, sorted by distance ascending."""
    return await get_nearby_drivers(redis, session, lat, lng, radius_km)
