"""FR-5: Trip Status

Rider or driver queries current trip state.

Acceptance:
- GET /rides/{trip_id} → 200 {trip_id, status, driver_id, pickup_lat, pickup_lng,
  dropoff_lat, dropoff_lng, fare_estimate, fare_actual, ...}
- Non-existent trip → 404
"""

from verify.acceptance.conftest import assert_201, assert_404, assert_json_200


class TestGetTrip:
    """GET /rides/{trip_id} — query trip state."""

    def test_get_pending_trip(self, client, rider_id, known_pickup, known_dropoff):
        """Newly created trip returns full details with PENDING status, null driver."""
        trip = assert_201(
            client.post(
                "/rides",
                json={
                    "pickup_lat": known_pickup["lat"],
                    "pickup_lng": known_pickup["lng"],
                    "dropoff_lat": known_dropoff["lat"],
                    "dropoff_lng": known_dropoff["lng"],
                    "rider_id": rider_id,
                },
            )
        )
        trip_id = trip["trip_id"]

        data = assert_json_200(client.get(f"/rides/{trip_id}"))

        assert data["trip_id"] == trip_id
        assert data["status"] == "PENDING"
        assert data["rider_id"] == rider_id
        assert data["driver_id"] is None
        assert data["pickup_lat"] == known_pickup["lat"]
        assert data["pickup_lng"] == known_pickup["lng"]
        assert data["dropoff_lat"] == known_dropoff["lat"]
        assert data["dropoff_lng"] == known_dropoff["lng"]
        assert isinstance(data["fare_estimate"], int)
        assert data["fare_estimate"] > 0
        assert data["fare_actual"] is None
        assert "created_at" in data
        assert data["picked_up_at"] is None
        assert data["completed_at"] is None

    def test_get_matched_trip(self, client, rider_id, known_pickup, known_dropoff, online_driver):
        """After matching, trip shows MATCHED status and assigned driver."""
        trip = assert_201(
            client.post(
                "/rides",
                json={
                    "pickup_lat": known_pickup["lat"],
                    "pickup_lng": known_pickup["lng"],
                    "dropoff_lat": known_dropoff["lat"],
                    "dropoff_lng": known_dropoff["lng"],
                    "rider_id": rider_id,
                },
            )
        )

        assert_json_200(client.post(f"/rides/{trip['trip_id']}/match"))

        data = assert_json_200(client.get(f"/rides/{trip['trip_id']}"))
        assert data["status"] == "MATCHED"
        assert data["driver_id"] == online_driver

    def test_get_completed_trip_shows_fare(
        self, client, rider_id, known_pickup, known_dropoff, driver_id
    ):
        """Completed trip shows fare_actual, completed_at, and COMPLETED status."""
        # Set up: create → match → pickup → complete
        assert_json_200(
            client.post(
                f"/drivers/{driver_id}/location",
                json={
                    "lat": known_pickup["lat"] + 0.001,
                    "lng": known_pickup["lng"],
                    "status": "ONLINE",
                },
            )
        )
        trip = assert_201(
            client.post(
                "/rides",
                json={
                    "pickup_lat": known_pickup["lat"],
                    "pickup_lng": known_pickup["lng"],
                    "dropoff_lat": known_dropoff["lat"],
                    "dropoff_lng": known_dropoff["lng"],
                    "rider_id": rider_id,
                },
            )
        )
        trip_id = trip["trip_id"]

        assert_json_200(client.post(f"/rides/{trip_id}/match"))
        assert_json_200(client.post(f"/rides/{trip_id}/pickup", json={"driver_id": driver_id}))
        assert_json_200(
            client.post(
                f"/rides/{trip_id}/complete",
                json={
                    "driver_id": driver_id,
                    "distance_km": 5.2,
                    "duration_minutes": 12,
                },
            )
        )

        data = assert_json_200(client.get(f"/rides/{trip_id}"))
        assert data["status"] == "COMPLETED"
        assert data["fare_actual"] is not None
        assert isinstance(data["fare_actual"], int)
        assert data["completed_at"] is not None
        assert data["picked_up_at"] is not None

    def test_nonexistent_trip_returns_404(self, client):
        assert_404(client.get("/rides/00000000-0000-0000-0000-000000000000"))


class TestTripStateTransitions:
    """Full lifecycle: PENDING → MATCHED → PICKED_UP → COMPLETED."""

    def test_full_lifecycle_transitions(
        self, client, rider_id, known_pickup, known_dropoff, online_driver
    ):
        """Walk through every state and verify GET reflects current state."""
        trip = assert_201(
            client.post(
                "/rides",
                json={
                    "pickup_lat": known_pickup["lat"],
                    "pickup_lng": known_pickup["lng"],
                    "dropoff_lat": known_dropoff["lat"],
                    "dropoff_lng": known_dropoff["lng"],
                    "rider_id": rider_id,
                },
            )
        )
        trip_id = trip["trip_id"]

        # PENDING
        assert_json_200(client.get(f"/rides/{trip_id}"))["status"] == "PENDING"

        # MATCHED
        assert_json_200(client.post(f"/rides/{trip_id}/match"))
        assert assert_json_200(client.get(f"/rides/{trip_id}"))["status"] == "MATCHED"

        # PICKED_UP
        assert_json_200(client.post(f"/rides/{trip_id}/pickup", json={"driver_id": online_driver}))
        status_data = assert_json_200(client.get(f"/rides/{trip_id}"))
        assert status_data["status"] == "PICKED_UP"
        assert status_data["picked_up_at"] is not None

        # COMPLETED
        assert_json_200(
            client.post(
                f"/rides/{trip_id}/complete",
                json={
                    "driver_id": online_driver,
                    "distance_km": 5.2,
                    "duration_minutes": 12,
                },
            )
        )
        final = assert_json_200(client.get(f"/rides/{trip_id}"))
        assert final["status"] == "COMPLETED"
        assert final["fare_actual"] is not None
        assert final["completed_at"] is not None
