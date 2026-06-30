"""Driver ORM model."""

from datetime import datetime
from uuid import UUID

from sqlalchemy import CheckConstraint, DateTime, Double, String, Text, func
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ..database import Base


class Driver(Base):
    __tablename__ = "drivers"
    __table_args__ = (
        CheckConstraint(
            "status IN ('ONLINE', 'BUSY', 'OFFLINE')",
            name="chk_driver_status",
        ),
    )

    driver_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid()
    )
    name: Mapped[str] = mapped_column(Text, nullable=False)
    vehicle_type: Mapped[str] = mapped_column(String(50), nullable=False, server_default="UberX")
    status: Mapped[str] = mapped_column(String(10), nullable=False, server_default="OFFLINE")
    lat: Mapped[float | None] = mapped_column(Double, nullable=True)
    lng: Mapped[float | None] = mapped_column(Double, nullable=True)
    last_ping: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    trips = relationship("Trip", back_populates="driver")
