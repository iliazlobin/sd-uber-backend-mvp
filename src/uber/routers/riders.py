"""Rider router: POST /riders."""

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from ..database import get_session
from ..models.rider import Rider
from ..schemas.rider import RiderCreate, RiderResponse

router = APIRouter(prefix="/riders", tags=["riders"])


@router.post("", status_code=201, response_model=RiderResponse)
async def create_rider(
    body: RiderCreate,
    session: AsyncSession = Depends(get_session),
):
    """Create a new rider."""
    rider = Rider(name=body.name)
    session.add(rider)
    await session.flush()
    await session.refresh(rider)
    return rider
