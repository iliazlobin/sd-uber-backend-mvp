"""FR-2: Match with Nearest Driver

System finds the nearest available driver and assigns them to the trip.

Acceptance:
- POST /rides/{trip_id}/match → 200 {driver_id, driver_location, distance_km, eta_estimate}
- If trip already matched → 409
- No available drivers within 5 km → 503
- Driver state atomically set ONLINE→BUSY (exactly-one assignment)
"""

import concurrent.futures

from verify.acceptance.conftest import (
    assert_201,
    assert_json_200,
)


class TestMatchDriverSuccess:
    """Happy-path: match PENDING trip to nearest ONLINE driver."""

    def test_match_returns_driver_info(
        self, client, rider_id, known_pickup, known_dropoff, online_driver
    ):
        # Create a trip
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

        # Match
        r = client.post(f"/rides/{trip_id}/match")
        data = assert_json_200(r, 200)

        assert "driver_id" in data
        assert data["driver_id"] == online_driver
        assert "driver_location" in data
        assert "lat" in data["driver_location"]
        assert "lng" in data["driver_location"]
        assert "distance_km" in data
        assert isinstance(data["distance_km"], int | float)
        assert "eta_estimate" in data
        assert isinstance(data["eta_estimate"], int)
        assert data["status"] == "MATCHED"

    def test_match_sets_trip_to_matched(
        self, client, rider_id, known_pickup, known_dropoff, online_driver
    ):
        """After matching, trip status should be MATCHED."""
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

        # Verify via GET
        status_data = assert_json_200(client.get(f"/rides/{trip_id}"))
        assert status_data["status"] == "MATCHED"
        assert status_data["driver_id"] == online_driver


class TestMatchDriverErrors:
    """Error cases: already matched, no drivers, non-existent trip."""

    def test_already_matched_returns_409(
        self, client, rider_id, known_pickup, known_dropoff, online_driver
    ):
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

        # First match succeeds
        assert_json_200(client.post(f"/rides/{trip['trip_id']}/match"))

        # Second match on same trip → 409
        r = client.post(f"/rides/{trip['trip_id']}/match")
        assert r.status_code == 409, f"Expected 409 on double match, got {r.status_code}: {r.text}"

    def test_no_available_drivers_returns_503(self, client, rider_id, known_pickup, known_dropoff):
        """No ONLINE drivers → 503."""
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

        r = client.post(f"/rides/{trip['trip_id']}/match")
        assert r.status_code == 503, f"Expected 503 with no drivers, got {r.status_code}: {r.text}"

    def test_nonexistent_trip_returns_404(self, client):
        r = client.post("/rides/00000000-0000-0000-0000-000000000000/match")
        assert r.status_code == 404, f"Expected 404, got {r.status_code}: {r.text}"


class TestExactlyOnceMatching:
    """Concurrent match attempts → exactly one succeeds (CAS on driver state)."""

    def test_concurrent_match_same_trip_one_succeeds(
        self, client, rider_id, known_pickup, known_dropoff, online_driver
    ):
        """Two concurrent match requests on the same trip: one 200, one 409."""
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

        def try_match():
            return client.post(f"/rides/{trip_id}/match")

        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
            futures = [executor.submit(try_match), executor.submit(try_match)]
            results = [f.result() for f in concurrent.futures.as_completed(futures)]

        status_codes = sorted(r.status_code for r in results)
        assert (
            status_codes == [200, 409]
        ), f"Expected [200, 409] for concurrent match, got {status_codes}: {[r.text for r in results]}"

    def test_driver_not_double_assigned(self, client, rider_id, known_pickup, known_dropoff):
        """Two concurrent trips trying to match → one driver assigned to only one trip."""
        # Create ONE online driver
        d = assert_201(
            client.post("/drivers", json={"name": "SoleDriver", "vehicle_type": "UberX"})
        )
        driver_id = d["driver_id"]
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

        # Create TWO trips with same pickup
        t1 = assert_201(
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
        t2 = assert_201(
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

        def match(trip_id):
            return client.post(f"/rides/{trip_id}/match")

        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
            f1 = executor.submit(match, t1["trip_id"])
            f2 = executor.submit(match, t2["trip_id"])
            r1 = f1.result()
            r2 = f2.result()

        # One should get 200, the other 503 (no more drivers)
        codes = {r1.status_code, r2.status_code}
        assert (
            200 in codes
        ), f"At least one match should succeed: {r1.status_code}:{r1.text}, {r2.status_code}:{r2.text}"

        # The driver should NOT be assigned to both trips
        if r1.status_code == 200:
            winning_trip = t1["trip_id"]
            losing_trip = t2["trip_id"]
        else:
            winning_trip = t2["trip_id"]
            losing_trip = t1["trip_id"]

        # Winning trip has the driver
        win_data = assert_json_200(client.get(f"/rides/{winning_trip}"))
        assert win_data["driver_id"] == driver_id

        # Losing trip should NOT have this driver
        lose_data = assert_json_200(client.get(f"/rides/{losing_trip}"))
        assert lose_data.get("driver_id") != driver_id
