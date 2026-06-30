"""Ride service: creation, Haversine fare estimation, status queries."""

import math
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models.rider import Rider
from ..models.trip import Trip
from ..schemas.ride import RideRequest


def haversine_km(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    """Compute great-circle distance in kilometres between two points."""
    R = 6371.0  # Earth radius in km
    dlat = math.radians(lat2 - lat1)
    dlng = math.radians(lng2 - lng1)
    a = (
        math.sin(dlat / 2) ** 2
        + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(dlng / 2) ** 2
    )
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    return R * c


FARE_RATE_CENTS_PER_KM = 150  # $1.50/km in cents


def compute_fare_estimate(
    pickup_lat: float, pickup_lng: float, dropoff_lat: float, dropoff_lng: float
) -> int:
    """Compute fare = Haversine distance (km) × $1.50/km, rounded to nearest cent."""
    dist = haversine_km(pickup_lat, pickup_lng, dropoff_lat, dropoff_lng)
    return round(dist * FARE_RATE_CENTS_PER_KM)


async def get_rider(session: AsyncSession, rider_id: UUID) -> Rider | None:
    """Fetch a rider by ID, or None if not found."""
    stmt = select(Rider).where(Rider.rider_id == rider_id)
    result = await session.execute(stmt)
    return result.scalar_one_or_none()


async def create_ride(session: AsyncSession, req: RideRequest) -> Trip:
    """Create a new PENDING trip with fare estimate.

    Raises:
        ValueError: if rider_id does not exist.
    """
    rider = await get_rider(session, req.rider_id)
    if rider is None:
        raise ValueError("Rider not found")

    fare = compute_fare_estimate(
        req.pickup_lat,
        req.pickup_lng,
        req.dropoff_lat,
        req.dropoff_lng,
    )

    trip = Trip(
        rider_id=req.rider_id,
        pickup_lat=req.pickup_lat,
        pickup_lng=req.pickup_lng,
        dropoff_lat=req.dropoff_lat,
        dropoff_lng=req.dropoff_lng,
        fare_estimate=fare,
        status="PENDING",
    )
    session.add(trip)
    await session.flush()
    await session.refresh(trip)
    return trip


async def get_ride(session: AsyncSession, trip_id: UUID) -> Trip | None:
    """Fetch a trip by ID, or None if not found."""
    stmt = select(Trip).where(Trip.trip_id == trip_id)
    result = await session.execute(stmt)
    return result.scalar_one_or_none()
