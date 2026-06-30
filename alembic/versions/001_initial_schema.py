"""initial schema: riders, drivers, trips

Revision ID: 001
Revises:
Create Date: 2026-06-26

"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "001"
down_revision: str | Sequence[str] | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "riders",
        sa.Column(
            "rider_id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.func.gen_random_uuid(),
        ),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )

    op.create_table(
        "drivers",
        sa.Column(
            "driver_id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.func.gen_random_uuid(),
        ),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column(
            "vehicle_type",
            sa.String(length=50),
            nullable=False,
            server_default=sa.text("'UberX'"),
        ),
        sa.Column(
            "status",
            sa.String(length=10),
            nullable=False,
            server_default=sa.text("'OFFLINE'"),
        ),
        sa.Column("lat", sa.Double(), nullable=True),
        sa.Column("lng", sa.Double(), nullable=True),
        sa.Column("last_ping", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint(
            "status IN ('ONLINE', 'BUSY', 'OFFLINE')",
            name="chk_driver_status",
        ),
    )

    op.create_table(
        "trips",
        sa.Column(
            "trip_id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.func.gen_random_uuid(),
        ),
        sa.Column(
            "rider_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("riders.rider_id"),
            nullable=False,
        ),
        sa.Column(
            "driver_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("drivers.driver_id"),
            nullable=True,
        ),
        sa.Column("pickup_lat", sa.Double(), nullable=False),
        sa.Column("pickup_lng", sa.Double(), nullable=False),
        sa.Column("dropoff_lat", sa.Double(), nullable=False),
        sa.Column("dropoff_lng", sa.Double(), nullable=False),
        sa.Column("fare_estimate", sa.Integer(), nullable=False),
        sa.Column("fare_actual", sa.Integer(), nullable=True),
        sa.Column(
            "status",
            sa.String(length=20),
            nullable=False,
            server_default=sa.text("'PENDING'"),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("picked_up_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "status IN ('PENDING', 'MATCHED', 'PICKED_UP', 'COMPLETED', 'CANCELLED')",
            name="chk_trip_status",
        ),
    )

    # Indexes per design.md
    op.create_index(
        "idx_trips_rider",
        "trips",
        ["rider_id", sa.text("created_at DESC")],
    )
    op.create_index(
        "idx_trips_driver",
        "trips",
        ["driver_id"],
        postgresql_where=sa.text("driver_id IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_table("trips")
    op.drop_table("drivers")
    op.drop_table("riders")
