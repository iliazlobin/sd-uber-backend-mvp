"""Unit tests for ride service: Haversine, fare estimation."""

import math

import pytest

from uber.services.ride_service import compute_fare_estimate, haversine_km


class TestHaversine:
    """Test the Haversine distance calculation."""

    def test_same_point_zero_distance(self):
        dist = haversine_km(40.7580, -73.9855, 40.7580, -73.9855)
        assert dist == 0.0

    def test_known_nyc_distance(self):
        """Times Square → Empire State Building: ~1.07 km."""
        dist = haversine_km(40.7580, -73.9855, 40.7484, -73.9857)
        assert 0.9 < dist < 1.2, f"Expected ~1.07 km, got {dist}"

    def test_long_distance(self):
        """NYC → LA: ~3940 km."""
        dist = haversine_km(40.7128, -74.0060, 34.0522, -118.2437)
        assert 3800 < dist < 4100, f"Expected ~3940 km, got {dist}"

    def test_antipodal(self):
        """Antipodal points: ~20015 km (half Earth circumference)."""
        dist = haversine_km(0, 0, 0, 180)
        assert 19000 < dist < 21000, f"Expected ~20015 km, got {dist}"


class TestFareEstimate:
    """Test fare calculation: Haversine distance × $1.50/km."""

    def test_fare_integer_cents(self):
        """Fare is returned as integer cents."""
        fare = compute_fare_estimate(40.7580, -73.9855, 40.7484, -73.9857)
        assert isinstance(fare, int)
        assert fare > 0

    def test_fare_reasonable_range(self):
        """~1.07 km × 150 c/km ≈ 160 cents."""
        fare = compute_fare_estimate(40.7580, -73.9855, 40.7484, -73.9857)
        assert 110 <= fare <= 210, f"Expected ~160, got {fare}"

    @pytest.mark.parametrize(
        "dist_km,expected_cents",
        [
            (1.0, 150),
            (5.0, 750),
            (10.0, 1500),
            (0.1, 15),
        ],
    )
    def test_fare_scales_linearly(self, dist_km, expected_cents):
        """Fare scales linearly with distance."""
        # At lat=0, 1° longitude = 111.32 km. At lat=40°, 1° = 111.32 * cos(40°) ≈ 85.3 km
        lng_per_km = 1.0 / (111.32 * math.cos(math.radians(0)))
        fare = compute_fare_estimate(0.0, 0.0, 0.0, dist_km * lng_per_km)
        # Allow ±2 cents for rounding
        assert (
            abs(fare - expected_cents) <= 2
        ), f"dist={dist_km} km: expected ~{expected_cents}, got {fare}"
