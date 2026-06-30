"""Driver service: CRUD, location updates (PG + Redis sync), nearby queries."""

from datetime import UTC, datetime
from uuid import UUID

from redis.asyncio import Redis
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from ..models.driver import Driver
from ..schemas.driver import DriverCreate, DriverLocationUpdate, NearbyDriverResponse


async def create_driver(session: AsyncSession, req: DriverCreate) -> Driver:
    """Create a new driver (OFFLINE by default)."""
    driver = Driver(name=req.name, vehicle_type=req.vehicle_type)
    session.add(driver)
    await session.flush()
    await session.refresh(driver)
    return driver


async def get_driver(session: AsyncSession, driver_id: UUID) -> Driver | None:
    """Fetch a driver by ID, or None if not found."""
    stmt = select(Driver).where(Driver.driver_id == driver_id)
    result = await session.execute(stmt)
    return result.scalar_one_or_none()


async def update_driver_location(
    session: AsyncSession,
    redis: Redis,
    driver_id: UUID,
    req: DriverLocationUpdate,
) -> Driver:
    """Update driver GPS and status in PostgreSQL, then sync to Redis.

    - ONLINE  → GEOADD to drivers:geo + SET driver:{id}:status ONLINE
    - BUSY / OFFLINE → ZREM from drivers:geo + SET driver:{id}:status
    """
    driver = await get_driver(session, driver_id)
    if driver is None:
        raise ValueError("Driver not found")

    now = datetime.now(UTC)

    stmt = (
        update(Driver)
        .where(Driver.driver_id == driver_id)
        .values(lat=req.lat, lng=req.lng, status=req.status, last_ping=now)
        .returning(Driver.driver_id, Driver.lat, Driver.lng, Driver.status, Driver.last_ping)
    )
    result = await session.execute(stmt)
    row = result.one()
    await session.flush()

    # Sync to Redis
    driver_id_str = str(driver_id)
    if req.status == "ONLINE":
        await redis.geoadd("drivers:geo", (req.lng, req.lat, driver_id_str))
        await redis.set(f"driver:{driver_id_str}:status", "ONLINE")
    else:
        await redis.zrem("drivers:geo", driver_id_str)
        await redis.set(f"driver:{driver_id_str}:status", req.status)

    # Build a refreshed Driver-like object from the returned row
    driver.lat = row.lat
    driver.lng = row.lng
    driver.status = row.status
    driver.last_ping = row.last_ping
    return driver


async def get_nearby_drivers(
    redis: Redis,
    session: AsyncSession,
    lat: float,
    lng: float,
    radius_km: float = 3.0,
) -> list[NearbyDriverResponse]:
    """Return ONLINE drivers within radius_km, sorted by distance ascending.

    Uses Redis GEORADIUS to find drivers in the proximity index, then
    filters by cached ONLINE status and enriches with PG data.
    """
    results = await redis.georadius(
        "drivers:geo",
        lng,
        lat,
        radius_km,
        unit="km",
        withdist=True,
        sort="ASC",
    )
    # results is [(member, distance), ...] where member is driver_id as string
    nearby = []
    for member, distance_km in results:
        driver_id_str = member
        # Double-check status in Redis cache
        status = await redis.get(f"driver:{driver_id_str}:status")
        if status != "ONLINE":
            continue

        # Fetch from PG for authoritative data
        driver = await get_driver(session, UUID(driver_id_str))
        if driver is None or driver.status != "ONLINE":
            continue

        nearby.append(
            NearbyDriverResponse(
                driver_id=driver.driver_id,
                lat=driver.lat,
                lng=driver.lng,
                status="ONLINE",
                distance_km=round(distance_km, 4),
            )
        )

    return nearby
