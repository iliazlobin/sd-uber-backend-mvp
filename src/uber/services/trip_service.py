"""Trip lifecycle service: pickup/complete FSM, fare calculation, driver release."""

from datetime import UTC, datetime
from uuid import UUID

from redis.asyncio import Redis
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from ..models.driver import Driver
from ..models.trip import Trip
from ..schemas.trip import TripCompleteResponse, TripPickupResponse

FARE_RATE_CENTS_PER_KM = 150  # $1.50/km


async def pickup_trip(
    session: AsyncSession,
    trip_id: UUID,
    driver_id: UUID,
) -> TripPickupResponse:
    """Transition trip from MATCHED → PICKED_UP.

    Raises:
        ValueError: trip not found
        RuntimeError: trip not in MATCHED state
        PermissionError: driver_id does not match trip's assigned driver
    """
    stmt = select(Trip).where(Trip.trip_id == trip_id)
    result = await session.execute(stmt)
    trip = result.scalar_one_or_none()

    if trip is None:
        raise ValueError("Trip not found")

    if trip.status != "MATCHED":
        raise RuntimeError("Trip is not in MATCHED state")

    if trip.driver_id != driver_id:
        raise PermissionError("Driver does not match assigned driver for this trip")

    now = datetime.now(UTC)
    upd_stmt = (
        update(Trip).where(Trip.trip_id == trip_id).values(status="PICKED_UP", picked_up_at=now)
    )
    await session.execute(upd_stmt)
    await session.flush()

    return TripPickupResponse(
        trip_id=trip_id,
        status="PICKED_UP",
        picked_up_at=now,
        driver_id=driver_id,
    )


async def complete_trip(
    session: AsyncSession,
    redis: Redis,
    trip_id: UUID,
    driver_id: UUID,
    distance_km: float,
    duration_minutes: int,
) -> TripCompleteResponse:
    """Transition trip from PICKED_UP → COMPLETED, compute fare, release driver.

    Fare = round(distance_km * FARE_RATE_CENTS_PER_KM) in integer cents.

    On completion:
    - Set driver status back to ONLINE in PG
    - GEOADD driver back to Redis + SET status ONLINE

    Raises:
        ValueError: trip not found, or invalid distance/duration
        RuntimeError: trip not in PICKED_UP state
        PermissionError: driver_id does not match trip's assigned driver
    """
    stmt = select(Trip).where(Trip.trip_id == trip_id)
    result = await session.execute(stmt)
    trip = result.scalar_one_or_none()

    if trip is None:
        raise ValueError("Trip not found")

    if trip.status != "PICKED_UP":
        raise RuntimeError("Trip is not in PICKED_UP state")

    if trip.driver_id != driver_id:
        raise PermissionError("Driver does not match assigned driver for this trip")

    if distance_km <= 0:
        raise ValueError("distance_km must be positive")

    if duration_minutes <= 0:
        raise ValueError("duration_minutes must be positive")

    fare = round(distance_km * FARE_RATE_CENTS_PER_KM)
    now = datetime.now(UTC)

    # Update trip to COMPLETED
    upd_stmt = (
        update(Trip)
        .where(Trip.trip_id == trip_id)
        .values(status="COMPLETED", fare_actual=fare, completed_at=now)
    )
    await session.execute(upd_stmt)

    # Release driver back to ONLINE
    driver_upd = update(Driver).where(Driver.driver_id == driver_id).values(status="ONLINE")
    await session.execute(driver_upd)
    await session.flush()

    # Sync driver back to Redis
    driver_stmt = select(Driver).where(Driver.driver_id == driver_id)
    drv_result = await session.execute(driver_stmt)
    driver = drv_result.scalar_one()

    driver_id_str = str(driver_id)
    await redis.geoadd("drivers:geo", (driver.lng, driver.lat, driver_id_str))
    await redis.set(f"driver:{driver_id_str}:status", "ONLINE")

    return TripCompleteResponse(
        trip_id=trip_id,
        status="COMPLETED",
        fare=fare,
        distance_km=distance_km,
        duration_minutes=duration_minutes,
        completed_at=now,
    )
