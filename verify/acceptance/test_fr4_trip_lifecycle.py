"""FR-4: Trip Lifecycle

Driver picks up rider and completes the trip. Receipt returned on completion.

Acceptance:
- POST /rides/{trip_id}/pickup {driver_id} → 200 {status: "PICKED_UP", picked_up_at}
- If not in MATCHED state → 409
- Wrong driver → 403
- POST /rides/{trip_id}/complete {driver_id, distance_km, duration_minutes} → 200
  {trip_id, fare, distance_km, duration_minutes, status: "COMPLETED"}
- If not in PICKED_UP state → 409
- Fare = straight-line distance × $1.50/km
"""

from verify.acceptance.conftest import (
    assert_201,
    assert_404,
    assert_json_200,
)


def _create_and_match(client, rider_id, pickup, dropoff, driver_id):
    """Helper: create a trip, set a driver ONLINE, match them."""
    # Set driver ONLINE near pickup
    assert_json_200(
        client.post(
            f"/drivers/{driver_id}/location",
            json={
                "lat": pickup["lat"] + 0.001,
                "lng": pickup["lng"],
                "status": "ONLINE",
            },
        )
    )

    trip = assert_201(
        client.post(
            "/rides",
            json={
                "pickup_lat": pickup["lat"],
                "pickup_lng": pickup["lng"],
                "dropoff_lat": dropoff["lat"],
                "dropoff_lng": dropoff["lng"],
                "rider_id": rider_id,
            },
        )
    )
    trip_id = trip["trip_id"]

    assert_json_200(client.post(f"/rides/{trip_id}/match"))
    return trip_id


class TestPickup:
    """POST /rides/{trip_id}/pickup — driver picks up rider."""

    def test_pickup_sets_status_to_picked_up(
        self, client, rider_id, known_pickup, known_dropoff, driver_id
    ):
        trip_id = _create_and_match(client, rider_id, known_pickup, known_dropoff, driver_id)

        r = client.post(f"/rides/{trip_id}/pickup", json={"driver_id": driver_id})
        data = assert_json_200(r)

        assert data["status"] == "PICKED_UP"
        assert "picked_up_at" in data
        assert data["driver_id"] == driver_id
        assert data["trip_id"] == trip_id

    def test_pickup_sets_picked_up_at_timestamp(
        self, client, rider_id, known_pickup, known_dropoff, driver_id
    ):
        trip_id = _create_and_match(client, rider_id, known_pickup, known_dropoff, driver_id)

        data = assert_json_200(
            client.post(f"/rides/{trip_id}/pickup", json={"driver_id": driver_id})
        )
        assert data["picked_up_at"] is not None

    def test_pickup_not_matched_returns_409(
        self, client, rider_id, known_pickup, known_dropoff, driver_id
    ):
        """Cannot pickup a trip that is still PENDING."""
        # Set driver ONLINE
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

        # Create trip but don't match
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

        r = client.post(f"/rides/{trip['trip_id']}/pickup", json={"driver_id": driver_id})
        assert r.status_code == 409, (
            f"Expected 409 for PENDING trip pickup, got {r.status_code}: {r.text}"
        )

    def test_wrong_driver_returns_403(
        self, client, rider_id, known_pickup, known_dropoff, driver_id
    ):
        """Driver B cannot pick up a trip assigned to Driver A."""
        trip_id = _create_and_match(client, rider_id, known_pickup, known_dropoff, driver_id)

        # Create a different driver
        other = assert_201(
            client.post("/drivers", json={"name": "WrongDriver", "vehicle_type": "UberX"})
        )

        r = client.post(f"/rides/{trip_id}/pickup", json={"driver_id": other["driver_id"]})
        assert r.status_code == 403, f"Expected 403 for wrong driver, got {r.status_code}: {r.text}"

    def test_pickup_nonexistent_trip_returns_404(self, client, driver_id):
        assert_404(
            client.post(
                "/rides/00000000-0000-0000-0000-000000000000/pickup",
                json={
                    "driver_id": driver_id,
                },
            )
        )


class TestComplete:
    """POST /rides/{trip_id}/complete — driver completes trip."""

    def test_complete_sets_status_to_completed(
        self, client, rider_id, known_pickup, known_dropoff, driver_id
    ):
        trip_id = _create_and_match(client, rider_id, known_pickup, known_dropoff, driver_id)

        # Pick up first
        assert_json_200(client.post(f"/rides/{trip_id}/pickup", json={"driver_id": driver_id}))

        # Complete
        r = client.post(
            f"/rides/{trip_id}/complete",
            json={
                "driver_id": driver_id,
                "distance_km": 5.2,
                "duration_minutes": 12,
            },
        )
        data = assert_json_200(r)

        assert data["status"] == "COMPLETED"
        assert data["trip_id"] == trip_id
        assert data["distance_km"] == 5.2
        assert data["duration_minutes"] == 12
        assert "fare" in data
        assert isinstance(data["fare"], int)
        assert "completed_at" in data
        assert data["completed_at"] is not None

    def test_fare_calculation(self, client, rider_id, known_pickup, known_dropoff, driver_id):
        """Fare = distance_km × $1.50/km = distance_km × 150 (in cents)."""
        trip_id = _create_and_match(client, rider_id, known_pickup, known_dropoff, driver_id)

        assert_json_200(client.post(f"/rides/{trip_id}/pickup", json={"driver_id": driver_id}))

        # distance_km = 5.2 → fare = round(5.2 * 150) = round(780) = 780 cents
        # distance_km = 10.0 → fare = round(10.0 * 150) = 1500 cents
        for dist, expected_cents in [(5.2, 780), (10.0, 1500), (3.33, 500)]:
            # Need a fresh trip for each test case
            t_id = _create_and_match(client, rider_id, known_pickup, known_dropoff, driver_id)
            assert_json_200(client.post(f"/rides/{t_id}/pickup", json={"driver_id": driver_id}))
            data = assert_json_200(
                client.post(
                    f"/rides/{t_id}/complete",
                    json={
                        "driver_id": driver_id,
                        "distance_km": dist,
                        "duration_minutes": 10,
                    },
                )
            )
            assert data["fare"] == expected_cents, (
                f"distance={dist} km: expected fare={expected_cents}, got {data['fare']}"
            )

    def test_complete_not_picked_up_returns_409(
        self, client, rider_id, known_pickup, known_dropoff, driver_id
    ):
        """Cannot complete a trip that is MATCHED but not PICKED_UP."""
        trip_id = _create_and_match(client, rider_id, known_pickup, known_dropoff, driver_id)

        # Don't pick up — try to complete directly
        r = client.post(
            f"/rides/{trip_id}/complete",
            json={
                "driver_id": driver_id,
                "distance_km": 5.0,
                "duration_minutes": 10,
            },
        )
        assert r.status_code == 409, (
            f"Expected 409 for completing MATCHED (not PICKED_UP) trip, got {r.status_code}: {r.text}"
        )

    def test_complete_wrong_driver_returns_403(
        self, client, rider_id, known_pickup, known_dropoff, driver_id
    ):
        """Driver B cannot complete a trip assigned to Driver A."""
        trip_id = _create_and_match(client, rider_id, known_pickup, known_dropoff, driver_id)
        assert_json_200(client.post(f"/rides/{trip_id}/pickup", json={"driver_id": driver_id}))

        other = assert_201(
            client.post("/drivers", json={"name": "WrongDriver", "vehicle_type": "UberX"})
        )
        r = client.post(
            f"/rides/{trip_id}/complete",
            json={
                "driver_id": other["driver_id"],
                "distance_km": 5.0,
                "duration_minutes": 10,
            },
        )
        assert r.status_code == 403, f"Expected 403 for wrong driver, got {r.status_code}: {r.text}"

    def test_complete_missing_fields_returns_422(
        self, client, rider_id, known_pickup, known_dropoff, driver_id
    ):
        trip_id = _create_and_match(client, rider_id, known_pickup, known_dropoff, driver_id)
        assert_json_200(client.post(f"/rides/{trip_id}/pickup", json={"driver_id": driver_id}))

        r = client.post(f"/rides/{trip_id}/complete", json={"driver_id": driver_id})
        assert r.status_code == 422, (
            f"Missing distance/duration: expected 422, got {r.status_code}: {r.text}"
        )

    def test_complete_nonexistent_trip_returns_404(self, client, driver_id):
        assert_404(
            client.post(
                "/rides/00000000-0000-0000-0000-000000000000/complete",
                json={
                    "driver_id": driver_id,
                    "distance_km": 5.0,
                    "duration_minutes": 10,
                },
            )
        )

    def test_complete_negative_distance_returns_422(
        self, client, rider_id, known_pickup, known_dropoff, driver_id
    ):
        trip_id = _create_and_match(client, rider_id, known_pickup, known_dropoff, driver_id)
        assert_json_200(client.post(f"/rides/{trip_id}/pickup", json={"driver_id": driver_id}))

        r = client.post(
            f"/rides/{trip_id}/complete",
            json={
                "driver_id": driver_id,
                "distance_km": -1.0,
                "duration_minutes": 10,
            },
        )
        assert r.status_code == 422, (
            f"Negative distance: expected 422, got {r.status_code}: {r.text}"
        )

    def test_driver_released_after_completion(
        self, client, rider_id, known_pickup, known_dropoff, driver_id
    ):
        """After completing a trip, driver should be ONLINE again (available for new matches)."""
        trip_id = _create_and_match(client, rider_id, known_pickup, known_dropoff, driver_id)
        assert_json_200(client.post(f"/rides/{trip_id}/pickup", json={"driver_id": driver_id}))
        assert_json_200(
            client.post(
                f"/rides/{trip_id}/complete",
                json={
                    "driver_id": driver_id,
                    "distance_km": 5.0,
                    "duration_minutes": 10,
                },
            )
        )

        # Driver should now appear in nearby results again
        r = client.get(
            "/drivers/nearby",
            params={
                "lat": known_pickup["lat"],
                "lng": known_pickup["lng"],
                "radius_km": 5,
            },
        )
        data = assert_json_200(r)
        driver_ids = [d["driver_id"] for d in data]
        assert driver_id in driver_ids, "Driver should be ONLINE again after trip completion"
