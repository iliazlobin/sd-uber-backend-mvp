"""Functional tests: end-to-end API tests using the ASGI test client.

These tests exercise the full stack: router → service → model → DB.
"""

from uuid import uuid4

import pytest


class TestRideFlow:
    """Full lifecycle: request → match → pickup → complete → status."""

    @pytest.mark.asyncio
    async def test_full_ride_lifecycle(self, client, session):
        """PENDING → MATCHED → PICKED_UP → COMPLETED."""
        # Create rider
        resp = await client.post("/riders", json={"name": "Alice"})
        assert resp.status_code == 201
        rider_id = resp.json()["rider_id"]

        # Create driver
        resp = await client.post("/drivers", json={"name": "Bob", "vehicle_type": "UberX"})
        assert resp.status_code == 201
        driver_id = resp.json()["driver_id"]

        # Set driver ONLINE
        resp = await client.post(
            f"/drivers/{driver_id}/location",
            json={"lat": 40.7590, "lng": -73.9845, "status": "ONLINE"},
        )
        assert resp.status_code == 200

        # Create ride
        resp = await client.post(
            "/rides",
            json={
                "pickup_lat": 40.7580,
                "pickup_lng": -73.9855,
                "dropoff_lat": 40.7484,
                "dropoff_lng": -73.9857,
                "rider_id": rider_id,
            },
        )
        assert resp.status_code == 201
        trip = resp.json()
        trip_id = trip["trip_id"]
        assert trip["status"] == "PENDING"
        assert trip["fare_estimate"] > 0

        # Match
        resp = await client.post(f"/rides/{trip_id}/match")
        assert resp.status_code == 200
        match = resp.json()
        assert match["driver_id"] == driver_id
        assert match["status"] == "MATCHED"
        assert match["eta_estimate"] > 0

        # Pickup
        resp = await client.post(
            f"/rides/{trip_id}/pickup",
            json={"driver_id": driver_id},
        )
        assert resp.status_code == 200
        assert resp.json()["status"] == "PICKED_UP"

        # Complete
        resp = await client.post(
            f"/rides/{trip_id}/complete",
            json={"driver_id": driver_id, "distance_km": 5.2, "duration_minutes": 12},
        )
        assert resp.status_code == 200
        complete = resp.json()
        assert complete["status"] == "COMPLETED"
        assert complete["fare"] == 780  # 5.2 * 150 = 780
        assert complete["completed_at"] is not None

        # Final status
        resp = await client.get(f"/rides/{trip_id}")
        assert resp.status_code == 200
        final = resp.json()
        assert final["status"] == "COMPLETED"
        assert final["fare_actual"] == 780


class TestValidation:
    """Input validation: missing fields, invalid values."""

    @pytest.mark.asyncio
    async def test_missing_coordinates_422(self, client):
        """Missing required fields return 422."""
        resp = await client.post("/rides", json={})
        assert resp.status_code == 422

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "field,value",
        [
            ("pickup_lat", 200),
            ("pickup_lng", -300),
            ("dropoff_lat", -91),
            ("dropoff_lng", 181),
        ],
    )
    async def test_invalid_coordinate_422(self, client, field, value):
        """Coordinates outside valid range return 422."""
        body = {
            "pickup_lat": 40.7580,
            "pickup_lng": -73.9855,
            "dropoff_lat": 40.7484,
            "dropoff_lng": -73.9857,
            "rider_id": str(uuid4()),
        }
        body[field] = value
        resp = await client.post("/rides", json=body)
        assert resp.status_code == 422


class TestStateMachine:
    """State machine guards: invalid transitions return 409/403."""

    @pytest.mark.asyncio
    async def test_cannot_pickup_pending(self, client, session):
        """Pickup on PENDING trip returns 409."""
        # Create rider
        resp = await client.post("/riders", json={"name": "Test"})
        assert resp.status_code == 201
        rider_id = resp.json()["rider_id"]

        # Create driver and set ONLINE
        resp = await client.post("/drivers", json={"name": "Test", "vehicle_type": "UberX"})
        assert resp.status_code == 201
        driver_id = resp.json()["driver_id"]
        resp = await client.post(
            f"/drivers/{driver_id}/location",
            json={"lat": 40.7590, "lng": -73.9845, "status": "ONLINE"},
        )
        assert resp.status_code == 200

        # Create PENDING trip
        resp = await client.post(
            "/rides",
            json={
                "pickup_lat": 40.7580,
                "pickup_lng": -73.9855,
                "dropoff_lat": 40.7484,
                "dropoff_lng": -73.9857,
                "rider_id": rider_id,
            },
        )
        assert resp.status_code == 201
        trip_id = resp.json()["trip_id"]

        # Try pickup on PENDING (not matched) → 409
        resp = await client.post(
            f"/rides/{trip_id}/pickup",
            json={"driver_id": driver_id},
        )
        assert resp.status_code == 409

    @pytest.mark.asyncio
    async def test_wrong_driver_403(self, client, session):
        """Wrong driver on pickup returns 403."""
        resp = await client.post("/riders", json={"name": "Test"})
        assert resp.status_code == 201
        rider_id = resp.json()["rider_id"]

        resp = await client.post("/drivers", json={"name": "GoodDriver", "vehicle_type": "UberX"})
        assert resp.status_code == 201
        good_driver = resp.json()["driver_id"]
        resp = await client.post(
            f"/drivers/{good_driver}/location",
            json={"lat": 40.7590, "lng": -73.9845, "status": "ONLINE"},
        )
        assert resp.status_code == 200

        resp = await client.post("/drivers", json={"name": "BadDriver", "vehicle_type": "UberX"})
        assert resp.status_code == 201
        bad_driver = resp.json()["driver_id"]

        resp = await client.post(
            "/rides",
            json={
                "pickup_lat": 40.7580,
                "pickup_lng": -73.9855,
                "dropoff_lat": 40.7484,
                "dropoff_lng": -73.9857,
                "rider_id": rider_id,
            },
        )
        assert resp.status_code == 201
        trip_id = resp.json()["trip_id"]

        # Match with good driver
        resp = await client.post(f"/rides/{trip_id}/match")
        assert resp.status_code == 200

        # Try pickup with bad driver
        resp = await client.post(
            f"/rides/{trip_id}/pickup",
            json={"driver_id": bad_driver},
        )
        assert resp.status_code == 403


class TestNearbyDrivers:
    """GET /drivers/nearby ordering and filtering."""

    @pytest.mark.asyncio
    async def test_busy_driver_excluded(self, client, session):
        """BUSY drivers should not appear in nearby results."""
        resp = await client.post("/drivers", json={"name": "BusyOne", "vehicle_type": "UberX"})
        assert resp.status_code == 201
        driver_id = resp.json()["driver_id"]

        resp = await client.post(
            f"/drivers/{driver_id}/location",
            json={"lat": 40.7590, "lng": -73.9845, "status": "BUSY"},
        )
        assert resp.status_code == 200

        resp = await client.get(
            "/drivers/nearby",
            params={
                "lat": 40.7580,
                "lng": -73.9855,
                "radius_km": 5,
            },
        )
        assert resp.status_code == 200
        busy_ids = [d["driver_id"] for d in resp.json() if d["driver_id"] == driver_id]
        assert len(busy_ids) == 0
