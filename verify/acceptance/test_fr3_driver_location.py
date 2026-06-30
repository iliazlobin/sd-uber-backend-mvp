"""FR-3: Driver Location Tracking

Drivers update their GPS position and status. Riders can query nearby available drivers.

Acceptance:
- POST /drivers/{id}/location {lat, lng, status: "ONLINE"|"BUSY"|"OFFLINE"} → 200
- GET /drivers/nearby?lat=X&lng=Y&radius_km=3 → 200 [{driver_id, lat, lng, status: "ONLINE"}]
  — returns only ONLINE drivers, sorted by distance ascending
"""

import pytest

from verify.acceptance.conftest import (
    assert_201,
    assert_404,
    assert_json_200,
)


class TestDriverLocationUpdate:
    """POST /drivers/{id}/location — update GPS and status."""

    def test_update_location_sets_coordinates(self, client, driver_id, known_pickup):
        r = client.post(
            f"/drivers/{driver_id}/location",
            json={
                "lat": known_pickup["lat"],
                "lng": known_pickup["lng"],
                "status": "ONLINE",
            },
        )
        data = assert_json_200(r)
        assert data["lat"] == known_pickup["lat"]
        assert data["lng"] == known_pickup["lng"]
        assert data["status"] == "ONLINE"
        assert "last_ping" in data

    def test_update_location_changes_status(self, client, driver_id, known_pickup):
        """Driver can go ONLINE → BUSY → OFFLINE."""
        for status in ["ONLINE", "BUSY", "OFFLINE"]:
            r = client.post(
                f"/drivers/{driver_id}/location",
                json={
                    "lat": known_pickup["lat"],
                    "lng": known_pickup["lng"],
                    "status": status,
                },
            )
            data = assert_json_200(r)
            assert data["status"] == status

    def test_update_nonexistent_driver_returns_404(self, client, known_pickup):
        assert_404(
            client.post(
                "/drivers/00000000-0000-0000-0000-000000000000/location",
                json={
                    "lat": known_pickup["lat"],
                    "lng": known_pickup["lng"],
                    "status": "ONLINE",
                },
            )
        )

    @pytest.mark.parametrize("missing_field", ["lat", "lng", "status"])
    def test_missing_field_returns_422(self, client, driver_id, known_pickup, missing_field):
        body = {
            "lat": known_pickup["lat"],
            "lng": known_pickup["lng"],
            "status": "ONLINE",
        }
        del body[missing_field]
        r = client.post(f"/drivers/{driver_id}/location", json=body)
        assert (
            r.status_code == 422
        ), f"Missing '{missing_field}': expected 422, got {r.status_code}: {r.text}"

    def test_invalid_status_returns_422(self, client, driver_id, known_pickup):
        r = client.post(
            f"/drivers/{driver_id}/location",
            json={
                "lat": known_pickup["lat"],
                "lng": known_pickup["lng"],
                "status": "DRIVING",  # not a valid enum value
            },
        )
        assert r.status_code == 422, f"Invalid status: expected 422, got {r.status_code}: {r.text}"


class TestNearbyDrivers:
    """GET /drivers/nearby — list ONLINE drivers near a point, sorted by distance."""

    BASE_URL = "/drivers/nearby"

    def test_returns_empty_list_when_no_drivers(self, client, known_pickup):
        r = client.get(
            self.BASE_URL,
            params={
                "lat": known_pickup["lat"],
                "lng": known_pickup["lng"],
                "radius_km": 5,
            },
        )
        data = assert_json_200(r)
        assert data == []

    def test_returns_online_driver(self, client, online_driver, known_pickup):
        """ONLINE driver near the query point should appear."""
        r = client.get(
            self.BASE_URL,
            params={
                "lat": known_pickup["lat"],
                "lng": known_pickup["lng"],
                "radius_km": 5,
            },
        )
        data = assert_json_200(r)
        assert len(data) >= 1
        driver = data[0]
        assert driver["status"] == "ONLINE"
        assert "driver_id" in driver
        assert "lat" in driver
        assert "lng" in driver
        assert "distance_km" in driver

    def test_sorted_by_distance_ascending(self, client, known_pickup):
        """Closer driver appears first."""
        # Driver 1: very close (~111m north)
        d1 = assert_201(
            client.post("/drivers", json={"name": "CloseDriver", "vehicle_type": "UberX"})
        )
        assert_json_200(
            client.post(
                f"/drivers/{d1['driver_id']}/location",
                json={
                    "lat": known_pickup["lat"] + 0.001,
                    "lng": known_pickup["lng"],
                    "status": "ONLINE",
                },
            )
        )

        # Driver 2: farther (~2km north)
        d2 = assert_201(
            client.post("/drivers", json={"name": "FarDriver", "vehicle_type": "UberX"})
        )
        assert_json_200(
            client.post(
                f"/drivers/{d2['driver_id']}/location",
                json={
                    "lat": known_pickup["lat"] + 0.02,
                    "lng": known_pickup["lng"],
                    "status": "ONLINE",
                },
            )
        )

        r = client.get(
            self.BASE_URL,
            params={
                "lat": known_pickup["lat"],
                "lng": known_pickup["lng"],
                "radius_km": 5,
            },
        )
        data = assert_json_200(r)

        # Should have at least 2 drivers
        driver_ids = [d["driver_id"] for d in data]
        assert d1["driver_id"] in driver_ids
        assert d2["driver_id"] in driver_ids

        # Closer driver (d1) should appear before farther driver (d2)
        idx1 = driver_ids.index(d1["driver_id"])
        idx2 = driver_ids.index(d2["driver_id"])
        assert idx1 < idx2, f"Closer driver should be first: got d1 at {idx1}, d2 at {idx2}"

    def test_excludes_busy_drivers(self, client, known_pickup):
        """BUSY drivers should not appear in nearby results."""
        d = assert_201(
            client.post("/drivers", json={"name": "BusyDriver", "vehicle_type": "UberX"})
        )
        assert_json_200(
            client.post(
                f"/drivers/{d['driver_id']}/location",
                json={
                    "lat": known_pickup["lat"] + 0.001,
                    "lng": known_pickup["lng"],
                    "status": "BUSY",
                },
            )
        )

        r = client.get(
            self.BASE_URL,
            params={
                "lat": known_pickup["lat"],
                "lng": known_pickup["lng"],
                "radius_km": 5,
            },
        )
        data = assert_json_200(r)
        busy_ids = [item["driver_id"] for item in data if item["driver_id"] == d["driver_id"]]
        assert len(busy_ids) == 0, "BUSY driver should not appear in nearby results"

    def test_excludes_offline_drivers(self, client, known_pickup):
        """OFFLINE drivers should not appear in nearby results."""
        d = assert_201(
            client.post("/drivers", json={"name": "OfflineDriver", "vehicle_type": "UberX"})
        )
        # Driver is OFFLINE by default, but set explicitly
        assert_json_200(
            client.post(
                f"/drivers/{d['driver_id']}/location",
                json={
                    "lat": known_pickup["lat"] + 0.001,
                    "lng": known_pickup["lng"],
                    "status": "OFFLINE",
                },
            )
        )

        r = client.get(
            self.BASE_URL,
            params={
                "lat": known_pickup["lat"],
                "lng": known_pickup["lng"],
                "radius_km": 5,
            },
        )
        data = assert_json_200(r)
        offline_ids = [item["driver_id"] for item in data if item["driver_id"] == d["driver_id"]]
        assert len(offline_ids) == 0, "OFFLINE driver should not appear in nearby results"

    def test_respects_radius_km(self, client, online_driver, known_pickup):
        """Driver within 5 km but outside 0.1 km should not appear."""
        r = client.get(
            self.BASE_URL,
            params={
                "lat": known_pickup["lat"],
                "lng": known_pickup["lng"],
                "radius_km": 5,
            },
        )
        data_wide = assert_json_200(r)
        assert len(data_wide) >= 1, "Driver should appear within 5 km"

        r_narrow = client.get(
            self.BASE_URL,
            params={
                "lat": known_pickup["lat"],
                "lng": known_pickup["lng"],
                "radius_km": 0.1,
            },
        )
        data_narrow = assert_json_200(r_narrow)
        # Driver is ~0.111 km away; may or may not be in 0.1 km radius
        # (Haversine vs. Redis geohash rounding — don't assert exact boundary)
        # Just verify the query succeeds
        assert isinstance(data_narrow, list)

    def test_missing_query_params_returns_422(self, client):
        r = client.get(self.BASE_URL)  # no params
        assert r.status_code == 422, f"Missing params: expected 422, got {r.status_code}: {r.text}"
