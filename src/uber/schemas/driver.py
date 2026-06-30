"""Driver request/response schemas."""

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field


class DriverCreate(BaseModel):
    name: str
    vehicle_type: str = "UberX"


class DriverResponse(BaseModel):
    driver_id: UUID
    name: str
    vehicle_type: str
    status: str
    lat: float | None = None
    lng: float | None = None
    last_ping: datetime | None = None
    created_at: datetime

    model_config = {"from_attributes": True}


class DriverLocationUpdate(BaseModel):
    lat: float = Field(ge=-90, le=90)
    lng: float = Field(ge=-180, le=180)
    status: Literal["ONLINE", "BUSY", "OFFLINE"]


class DriverLocationResponse(BaseModel):
    driver_id: UUID
    lat: float
    lng: float
    status: str
    last_ping: datetime

    model_config = {"from_attributes": True}


class NearbyDriverResponse(BaseModel):
    driver_id: UUID
    lat: float
    lng: float
    status: str
    distance_km: float
