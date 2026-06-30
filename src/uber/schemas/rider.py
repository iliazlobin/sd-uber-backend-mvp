"""Rider request/response schemas."""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel


class RiderCreate(BaseModel):
    name: str


class RiderResponse(BaseModel):
    rider_id: UUID
    name: str
    created_at: datetime

    model_config = {"from_attributes": True}
