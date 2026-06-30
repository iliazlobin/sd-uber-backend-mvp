"""Trip ORM model."""

from datetime import datetime
from uuid import UUID

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    Double,
    ForeignKey,
    Integer,
    String,
    func,
)
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ..database import Base


class Trip(Base):
    __tablename__ = "trips"
    __table_args__ = (
        CheckConstraint(
            "status IN ('PENDING', 'MATCHED', 'PICKED_UP', 'COMPLETED', 'CANCELLED')",
            name="chk_trip_status",
        ),
    )

    trip_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid()
    )
    rider_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("riders.rider_id"), nullable=False
    )
    driver_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("drivers.driver_id"), nullable=True
    )
    pickup_lat: Mapped[float] = mapped_column(Double, nullable=False)
    pickup_lng: Mapped[float] = mapped_column(Double, nullable=False)
    dropoff_lat: Mapped[float] = mapped_column(Double, nullable=False)
    dropoff_lng: Mapped[float] = mapped_column(Double, nullable=False)
    fare_estimate: Mapped[int] = mapped_column(Integer, nullable=False)
    fare_actual: Mapped[int | None] = mapped_column(Integer, nullable=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False, server_default="PENDING")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    picked_up_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    rider = relationship("Rider", back_populates="trips")
    driver = relationship("Driver", back_populates="trips")
