"""FR-1: Request a Ride

Rider sets pickup/dropoff coordinates and receives a trip with fare estimate.

Acceptance:
- POST /rides {pickup_lat, pickup_lng, dropoff_lat, dropoff_lng, rider_id} → 201 {trip_id, fare_estimate, status: "PENDING"}
- Missing fields → 422
- Invalid coordinates → 422
- Non-existent rider → 404
"""

import pytest

from verify.acceptance.conftest import assert_201, assert_404


class TestRequestRideSuccess:
    """Happy-path: valid request returns 201 with trip data."""

    def test_request_ride_creates_trip_with_pending_status(
        self, client, rider_id, known_pickup, known_dropoff
    ):
        body = {
            "pickup_lat": known_pickup["lat"],
            "pickup_lng": known_pickup["lng"],
            "dropoff_lat": known_dropoff["lat"],
            "dropoff_lng": known_dropoff["lng"],
            "rider_id": rider_id,
        }
        r = client.post("/rides", json=body)
        data = assert_201(r)

        assert "trip_id" in data
        assert data["status"] == "PENDING"
        assert isinstance(data["fare_estimate"], int)
        assert data["fare_estimate"] > 0
        assert data["pickup_lat"] == known_pickup["lat"]
        assert data["pickup_lng"] == known_pickup["lng"]
        assert data["dropoff_lat"] == known_dropoff["lat"]
        assert data["dropoff_lng"] == known_dropoff["lng"]
        assert "created_at" in data

    def test_fare_estimate_is_reasonable(self, client, rider_id, known_pickup, known_dropoff):
        """Fare = straight-line Haversine distance × $1.50/km (150 cents/km).
        Times Square → Empire State Building ≈ 1.07 km → ~160 cents."""
        body = {
            "pickup_lat": known_pickup["lat"],
            "pickup_lng": known_pickup["lng"],
            "dropoff_lat": known_dropoff["lat"],
            "dropoff_lng": known_dropoff["lng"],
            "rider_id": rider_id,
        }
        data = assert_201(client.post("/rides", json=body))
        fare = data["fare_estimate"]
        # 1.07 km × 150 cents/km ≈ 160 cents. Allow ±30% for Haversine rounding.
        assert 110 <= fare <= 210, f"Expected fare around 160, got {fare}"


class TestRequestRideValidation:
    """Input validation: missing fields, invalid coordinates."""

    @pytest.mark.parametrize(
        "missing_field",
        [
            "pickup_lat",
            "pickup_lng",
            "dropoff_lat",
            "dropoff_lng",
            "rider_id",
        ],
    )
    def test_missing_required_field_returns_422(
        self, client, rider_id, known_pickup, known_dropoff, missing_field
    ):
        body = {
            "pickup_lat": known_pickup["lat"],
            "pickup_lng": known_pickup["lng"],
            "dropoff_lat": known_dropoff["lat"],
            "dropoff_lng": known_dropoff["lng"],
            "rider_id": rider_id,
        }
        del body[missing_field]
        r = client.post("/rides", json=body)
        assert (
            r.status_code == 422
        ), f"Missing '{missing_field}': expected 422, got {r.status_code}: {r.text}"

    @pytest.mark.parametrize(
        "field,value",
        [
            ("pickup_lat", 200),  # outside [-90, 90]
            ("pickup_lat", -200),
            ("pickup_lng", 300),  # outside [-180, 180]
            ("pickup_lng", -300),
            ("dropoff_lat", 91),
            ("dropoff_lat", -91),
            ("dropoff_lng", 181),
            ("dropoff_lng", -181),
        ],
    )
    def test_invalid_coordinate_returns_422(
        self, client, rider_id, known_pickup, known_dropoff, field, value
    ):
        body = {
            "pickup_lat": known_pickup["lat"],
            "pickup_lng": known_pickup["lng"],
            "dropoff_lat": known_dropoff["lat"],
            "dropoff_lng": known_dropoff["lng"],
            "rider_id": rider_id,
        }
        body[field] = value
        r = client.post("/rides", json=body)
        assert r.status_code == 422, f"{field}={value}: expected 422, got {r.status_code}: {r.text}"

    def test_nonexistent_rider_returns_404(self, client, known_pickup, known_dropoff):
        """Non-existent rider_id → 404."""
        body = {
            "pickup_lat": known_pickup["lat"],
            "pickup_lng": known_pickup["lng"],
            "dropoff_lat": known_dropoff["lat"],
            "dropoff_lng": known_dropoff["lng"],
            "rider_id": "00000000-0000-0000-0000-000000000000",
        }
        assert_404(client.post("/rides", json=body))

    def test_empty_json_body_returns_422(self, client):
        r = client.post("/rides", json={})
        assert r.status_code == 422, f"Empty body: expected 422, got {r.status_code}: {r.text}"
