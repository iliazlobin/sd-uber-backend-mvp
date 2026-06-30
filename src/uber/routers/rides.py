"""Rides router: POST, GET, match, pickup, complete."""

from uuid import UUID as _UUID

from fastapi import APIRouter, Depends, HTTPException
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from ..database import get_session
from ..redis_client import get_redis
from ..schemas.ride import RideMatchResponse, RideRequest, RideResponse
from ..schemas.trip import (
    TripCompleteRequest,
    TripCompleteResponse,
    TripPickupRequest,
    TripPickupResponse,
    TripResponse,
)
from ..services import matching_service, ride_service, trip_service

router = APIRouter(prefix="/rides", tags=["rides"])


# ── FR-1: Request a Ride ──────────────────────────────────────────


@router.post("", status_code=201, response_model=RideResponse)
async def request_ride(
    body: RideRequest,
    session: AsyncSession = Depends(get_session),
):
    """Create a new trip with fare estimate (Haversine × $1.50/km)."""
    try:
        trip = await ride_service.create_ride(session, body)
    except ValueError:
        raise HTTPException(status_code=404, detail="Rider not found") from None

    return trip


# ── FR-5: Trip Status ─────────────────────────────────────────────


@router.get("/{trip_id}", response_model=TripResponse)
async def get_ride(
    trip_id: str,
    session: AsyncSession = Depends(get_session),
):
    """Get full trip details."""
    try:
        tid = _UUID(trip_id)
    except ValueError:
        raise HTTPException(status_code=404, detail="Trip not found") from None

    trip = await ride_service.get_ride(session, tid)
    if trip is None:
        raise HTTPException(status_code=404, detail="Trip not found")
    return trip


# ── FR-2: Match with Nearest Driver ───────────────────────────────


@router.post("/{trip_id}/match", response_model=RideMatchResponse)
async def match_ride(
    trip_id: str,
    session: AsyncSession = Depends(get_session),
    redis: Redis = Depends(get_redis),
):
    """Match trip to nearest available ONLINE driver (Redis GEORADIUS + PG CAS)."""
    try:
        tid = _UUID(trip_id)
    except ValueError:
        raise HTTPException(status_code=404, detail="Trip not found") from None

    try:
        return await matching_service.match_ride(session, redis, tid)
    except ValueError:
        raise HTTPException(status_code=404, detail="Trip not found") from None
    except RuntimeError:
        raise HTTPException(status_code=409, detail="Trip is not in PENDING state") from None
    except LookupError:
        raise HTTPException(status_code=503, detail="No available drivers within 5 km") from None


# ── FR-4: Trip Lifecycle ──────────────────────────────────────────


@router.post("/{trip_id}/pickup", response_model=TripPickupResponse)
async def pickup_ride(
    trip_id: str,
    body: TripPickupRequest,
    session: AsyncSession = Depends(get_session),
):
    """Driver picks up the rider (MATCHED → PICKED_UP)."""
    try:
        tid = _UUID(trip_id)
    except ValueError:
        raise HTTPException(status_code=404, detail="Trip not found") from None

    try:
        return await trip_service.pickup_trip(session, tid, body.driver_id)
    except ValueError:
        raise HTTPException(status_code=404, detail="Trip not found") from None
    except RuntimeError:
        raise HTTPException(status_code=409, detail="Trip is not in MATCHED state") from None
    except PermissionError:
        raise HTTPException(
            status_code=403,
            detail="Driver does not match assigned driver for this trip",
        )


@router.post("/{trip_id}/complete", response_model=TripCompleteResponse)
async def complete_ride(
    trip_id: str,
    body: TripCompleteRequest,
    session: AsyncSession = Depends(get_session),
    redis: Redis = Depends(get_redis),
):
    """Driver completes the trip (PICKED_UP → COMPLETED), returns receipt."""
    try:
        tid = _UUID(trip_id)
    except ValueError:
        raise HTTPException(status_code=404, detail="Trip not found") from None

    try:
        return await trip_service.complete_trip(
            session,
            redis,
            tid,
            body.driver_id,
            body.distance_km,
            body.duration_minutes,
        )
    except ValueError as e:
        msg = str(e)
        if msg == "Trip not found":
            raise HTTPException(status_code=404, detail=msg) from None
        raise HTTPException(
            status_code=422,
            detail=[
                {
                    "loc": ["body", "distance_km"],
                    "msg": msg,
                    "type": "value_error",
                }
            ],
        )
    except RuntimeError:
        raise HTTPException(status_code=409, detail="Trip is not in PICKED_UP state") from None
    except PermissionError:
        raise HTTPException(
            status_code=403,
            detail="Driver does not match assigned driver for this trip",
        )
