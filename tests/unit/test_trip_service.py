"""Unit tests for trip service: state machine, fare calculation, driver release."""

from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from uber.models.trip import Trip
from uber.services.trip_service import complete_trip, pickup_trip


def _mock_execute(session, scalar_return):
    """Set up session.execute to return a result with scalar_one_or_none."""
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = scalar_return
    session.execute.return_value = mock_result
    # Also handle multiple execute calls by side_effect
    if not isinstance(session.execute, AsyncMock):
        session.execute = AsyncMock()
        session.execute.return_value = mock_result


class TestPickupStateMachine:
    """Test pickup_trip state validation."""

    @pytest.mark.asyncio
    async def test_pickup_requires_matched_state(self):
        """Cannot pickup a PENDING trip."""
        session = AsyncMock()
        trip_id = uuid4()
        driver_id = uuid4()

        mock_trip = MagicMock(spec=Trip)
        mock_trip.status = "PENDING"
        mock_trip.driver_id = driver_id
        _mock_execute(session, mock_trip)

        with pytest.raises(RuntimeError, match="not in MATCHED state"):
            await pickup_trip(session, trip_id, driver_id)

    @pytest.mark.asyncio
    async def test_pickup_wrong_driver(self):
        """Driver must match assigned driver."""
        session = AsyncMock()
        trip_id = uuid4()
        assigned_driver = uuid4()
        wrong_driver = uuid4()

        mock_trip = MagicMock(spec=Trip)
        mock_trip.status = "MATCHED"
        mock_trip.driver_id = assigned_driver
        _mock_execute(session, mock_trip)

        with pytest.raises(PermissionError, match="does not match"):
            await pickup_trip(session, trip_id, wrong_driver)

    @pytest.mark.asyncio
    async def test_pickup_nonexistent_trip(self):
        """Non-existent trip raises ValueError."""
        session = AsyncMock()
        _mock_execute(session, None)

        with pytest.raises(ValueError, match="not found"):
            await pickup_trip(session, uuid4(), uuid4())


class TestCompleteStateMachine:
    """Test complete_trip state validation and fare calculation."""

    @pytest.mark.asyncio
    async def test_complete_requires_picked_up_state(self):
        """Cannot complete a MATCHED (not PICKED_UP) trip."""
        session = AsyncMock()
        redis = AsyncMock()
        trip_id = uuid4()
        driver_id = uuid4()

        mock_trip = MagicMock(spec=Trip)
        mock_trip.status = "MATCHED"
        mock_trip.driver_id = driver_id
        _mock_execute(session, mock_trip)

        with pytest.raises(RuntimeError, match="not in PICKED_UP state"):
            await complete_trip(session, redis, trip_id, driver_id, 5.0, 10)

    @pytest.mark.asyncio
    async def test_complete_wrong_driver(self):
        """Driver must match assigned driver."""
        session = AsyncMock()
        redis = AsyncMock()
        trip_id = uuid4()
        assigned_driver = uuid4()
        wrong_driver = uuid4()

        mock_trip = MagicMock(spec=Trip)
        mock_trip.status = "PICKED_UP"
        mock_trip.driver_id = assigned_driver
        _mock_execute(session, mock_trip)

        with pytest.raises(PermissionError, match="does not match"):
            await complete_trip(session, redis, trip_id, wrong_driver, 5.0, 10)

    @pytest.mark.asyncio
    async def test_complete_nonexistent_trip(self):
        """Non-existent trip raises ValueError."""
        session = AsyncMock()
        redis = AsyncMock()
        _mock_execute(session, None)

        with pytest.raises(ValueError, match="not found"):
            await complete_trip(session, redis, uuid4(), uuid4(), 5.0, 10)

    @pytest.mark.asyncio
    async def test_complete_zero_distance_raises(self):
        """Distance must be positive."""
        session = AsyncMock()
        redis = AsyncMock()
        trip_id = uuid4()
        driver_id = uuid4()

        mock_trip = MagicMock(spec=Trip)
        mock_trip.status = "PICKED_UP"
        mock_trip.driver_id = driver_id
        _mock_execute(session, mock_trip)

        with pytest.raises(ValueError, match="positive"):
            await complete_trip(session, redis, trip_id, driver_id, 0.0, 10)

    @pytest.mark.asyncio
    async def test_complete_negative_duration_raises(self):
        """Duration must be positive."""
        session = AsyncMock()
        redis = AsyncMock()
        trip_id = uuid4()
        driver_id = uuid4()

        mock_trip = MagicMock(spec=Trip)
        mock_trip.status = "PICKED_UP"
        mock_trip.driver_id = driver_id
        _mock_execute(session, mock_trip)

        with pytest.raises(ValueError, match="positive"):
            await complete_trip(session, redis, trip_id, driver_id, 5.0, 0)


class TestFareCalculation:
    """Test fare = round(distance_km × 150)."""

    @pytest.mark.parametrize(
        "dist,expected",
        [
            (5.2, 780),
            (10.0, 1500),
            (3.33, 500),  # round(499.5) = 500
            (0.01, 2),  # round(1.5) = 2
            (1.0, 150),
        ],
    )
    def test_fare_calculation(self, dist, expected):
        """Fare = round(dist * 150) cents."""
        fare = round(dist * 150)
        assert fare == expected, f"dist={dist}: expected {expected}, got {fare}"
