"""Trip lifecycle request/response schemas."""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field


class TripPickupRequest(BaseModel):
    driver_id: UUID


class TripPickupResponse(BaseModel):
    trip_id: UUID
    status: str
    picked_up_at: datetime
    driver_id: UUID


class TripCompleteRequest(BaseModel):
    driver_id: UUID
    distance_km: float = Field(gt=0)
    duration_minutes: int = Field(gt=0)


class TripCompleteResponse(BaseModel):
    trip_id: UUID
    status: str
    fare: int
    distance_km: float
    duration_minutes: int
    completed_at: datetime


class TripResponse(BaseModel):
    trip_id: UUID
    rider_id: UUID
    driver_id: UUID | None = None
    status: str
    pickup_lat: float
    pickup_lng: float
    dropoff_lat: float
    dropoff_lng: float
    fare_estimate: int
    fare_actual: int | None = None
    created_at: datetime
    picked_up_at: datetime | None = None
    completed_at: datetime | None = None

    model_config = {"from_attributes": True}
