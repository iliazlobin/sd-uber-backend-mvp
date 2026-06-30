"""Ride request/response schemas."""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field


class RideRequest(BaseModel):
    pickup_lat: float = Field(ge=-90, le=90)
    pickup_lng: float = Field(ge=-180, le=180)
    dropoff_lat: float = Field(ge=-90, le=90)
    dropoff_lng: float = Field(ge=-180, le=180)
    rider_id: UUID


class RideResponse(BaseModel):
    trip_id: UUID
    fare_estimate: int
    status: str
    created_at: datetime
    pickup_lat: float
    pickup_lng: float
    dropoff_lat: float
    dropoff_lng: float

    model_config = {"from_attributes": True}


class RideMatchResponse(BaseModel):
    driver_id: UUID
    driver_location: dict
    distance_km: float
    eta_estimate: int
    status: str
