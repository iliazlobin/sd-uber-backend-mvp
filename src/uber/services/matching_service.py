"""Matching service: Redis GEORADIUS → PG CAS loop for exactly-once driver assignment."""

import math
from uuid import UUID

from redis.asyncio import Redis
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from ..models.driver import Driver
from ..models.trip import Trip
from ..schemas.ride import RideMatchResponse

MATCH_RADIUS_KM = 5.0
# ETA: assume ~30 km/h average urban speed → 2 min per km → 120 seconds per km
ETA_SECONDS_PER_KM = 120


def compute_eta_seconds(distance_km: float) -> int:
    """Simple linear ETA: ceil(distance_km * 120) seconds."""
    return max(1, math.ceil(distance_km * ETA_SECONDS_PER_KM))


async def match_ride(
    session: AsyncSession,
    redis: Redis,
    trip_id: UUID,
) -> RideMatchResponse:
    """Match a PENDING trip to the nearest available ONLINE driver.

    Algorithm:
    1. Verify trip exists and is PENDING (→ 409 if not)
    2. GEORADIUS drivers:geo for drivers within 5 km of pickup
    3. For each candidate (sorted by distance): CAS UPDATE driver status
       ONLINE → BUSY. First success wins.
    4. CAS UPDATE trip WHERE status='PENDING' → status='MATCHED', driver_id=X
    5. On success: remove driver from Redis GEO, set status BUSY in cache
    6. On trip-CAS failure: roll back driver CAS, return 409
    7. Return match response

    Raises:
        ValueError: trip not found
        RuntimeError: trip not in PENDING state
        LookupError: no available drivers within radius
    """
    # 1. Load trip
    stmt = select(Trip).where(Trip.trip_id == trip_id)
    result = await session.execute(stmt)
    trip = result.scalar_one_or_none()

    if trip is None:
        raise ValueError("Trip not found")

    if trip.status != "PENDING":
        raise RuntimeError("Trip is not in PENDING state")

    # 2. GEORADIUS for nearby ONLINE drivers
    geo_results = await redis.georadius(
        "drivers:geo",
        trip.pickup_lng,
        trip.pickup_lat,
        MATCH_RADIUS_KM,
        unit="km",
        withdist=True,
        sort="ASC",
    )

    if not geo_results:
        # No drivers in proximity index.
        # Re-check trip status — a concurrent request may have already
        # matched this trip and removed the driver from GEO.
        await session.refresh(trip)
        if trip.status != "PENDING":
            raise RuntimeError("Trip is not in PENDING state")
        raise LookupError("No available drivers within 5 km")

    # 3. CAS loop: try each driver in distance order.
    # Check Redis status to skip drivers already taken by concurrent requests.
    # Do NOT remove from Redis GEO when matched — just mark BUSY so
    # subsequent GEORADIUS calls still find the driver and can skip it.
    matched_driver_id = None
    matched_distance_km = None
    matched_driver_str = None

    for member, distance_km in geo_results:
        driver_id_str = member
        driver_uuid = UUID(driver_id_str)

        # Atomic CAS: UPDATE drivers SET status='BUSY' WHERE driver_id=X AND status='ONLINE' RETURNING *
        cas_stmt = (
            update(Driver)
            .where(Driver.driver_id == driver_uuid, Driver.status == "ONLINE")
            .values(status="BUSY")
            .returning(Driver.driver_id, Driver.lat, Driver.lng)
        )
        cas_result = await session.execute(cas_stmt)
        row = cas_result.one_or_none()

        if row is not None:
            # CAS succeeded — this driver is ours
            matched_driver_id = row.driver_id
            matched_distance_km = distance_km
            matched_driver_str = driver_id_str
            await session.flush()
            break

    if matched_driver_id is None:
        # CAS loop exhausted all candidates.
        # Re-check trip status — another concurrent request may have
        # already matched this trip while we were processing.
        await session.refresh(trip)
        if trip.status != "PENDING":
            raise RuntimeError("Trip is not in PENDING state")
        raise LookupError("No available drivers within 5 km")

    # 4. Update trip — atomic CAS to prevent double-matching
    trip_stmt = (
        update(Trip)
        .where(Trip.trip_id == trip_id, Trip.status == "PENDING")
        .values(driver_id=matched_driver_id, status="MATCHED")
        .returning(Trip.trip_id)
    )
    trip_result = await session.execute(trip_stmt)
    if trip_result.one_or_none() is None:
        # Another request matched this trip while we were processing.
        # Roll back the driver CAS.
        rollback_stmt = (
            update(Driver).where(Driver.driver_id == matched_driver_id).values(status="ONLINE")
        )
        await session.execute(rollback_stmt)
        await session.flush()
        raise RuntimeError("Trip is not in PENDING state")

    # 5. Trip CAS succeeded — mark driver BUSY in Redis cache.
    # Keep driver in GEO so subsequent GEORADIUS returns it; the status
    # check in the CAS loop will skip BUSY drivers.
    await redis.set(f"driver:{matched_driver_str}:status", "BUSY")

    eta = compute_eta_seconds(matched_distance_km)

    # 6. Fetch driver location for response
    drv_stmt = select(Driver).where(Driver.driver_id == matched_driver_id)
    drv_result = await session.execute(drv_stmt)
    driver = drv_result.scalar_one()

    return RideMatchResponse(
        driver_id=matched_driver_id,
        driver_location={"lat": driver.lat, "lng": driver.lng},
        distance_km=round(matched_distance_km, 4),
        eta_estimate=eta,
        status="MATCHED",
    )
