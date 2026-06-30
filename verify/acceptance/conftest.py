"""Shared fixtures and helpers for the Uber MVP black-box acceptance suite.

These tests do NOT import `src.uber`. They talk to the running system
via HTTP at API_BASE_URL.
"""

import contextlib
import os

import httpx
import pytest

API_BASE_URL = os.environ.get("API_BASE_URL", "http://localhost:8000")


@pytest.fixture(scope="session")
def base_url():
    return API_BASE_URL


@pytest.fixture(scope="session")
def client(base_url):
    """Session-scoped httpx client for the entire acceptance run."""
    with httpx.Client(base_url=base_url, timeout=10) as c:
        yield c


# -- Cleanup: autouse fixture to prevent state leakage between test classes --


@pytest.fixture(scope="class", autouse=True)
def _cleanup_redis_between_classes(client):
    """Ensure Redis GEO index is clean between test classes.

    Marks all known ONLINE drivers as OFFLINE so no stale driver
    is picked up by GEORADIUS in a subsequent test class.
    """
    yield
    try:
        r = client.get(
            "/drivers/nearby",
            params={
                "lat": 40.7580,
                "lng": -73.9855,
                "radius_km": 50,
            },
        )
        if r.status_code == 200:
            for d in r.json():
                with contextlib.suppress(Exception):
                    client.post(
                        f"/drivers/{d['driver_id']}/location",
                        json={
                            "lat": 0.0,
                            "lng": 0.0,
                            "status": "OFFLINE",
                        },
                    )
    except Exception:
        pass


# -- Assertion helpers --


def assert_json_200(r, expected_status=200):
    """Assert status code and return parsed JSON."""
    assert r.status_code == expected_status, (
        f"Expected {expected_status}, got {r.status_code}: {r.text}"
    )
    return r.json()


def assert_201(r):
    return assert_json_200(r, 201)


def assert_422(r):
    assert r.status_code == 422, f"Expected 422, got {r.status_code}: {r.text}"
    return r.json()


def assert_404(r):
    assert r.status_code == 404, f"Expected 404, got {r.status_code}: {r.text}"
    return r.json()


def assert_403(r):
    assert r.status_code == 403, f"Expected 403, got {r.status_code}: {r.text}"
    return r.json()


def assert_409(r):
    assert r.status_code == 409, f"Expected 409, got {r.status_code}: {r.text}"
    return r.json()


def assert_503(r):
    assert r.status_code == 503, f"Expected 503, got {r.status_code}: {r.text}"
    return r.json()


# -- Test data fixtures --


@pytest.fixture(scope="session")
def known_pickup():
    """Fixed NYC coordinates used across all tests for consistency."""
    return {"lat": 40.7580, "lng": -73.9855}  # Times Square area


@pytest.fixture(scope="session")
def known_dropoff():
    return {"lat": 40.7484, "lng": -73.9857}  # Empire State Building area (~1.07 km away)


@pytest.fixture(scope="session")
def rider_id(client):
    """Create one test rider, return its ID."""
    r = client.post("/riders", json={"name": "TestRider"})
    assert r.status_code == 201, f"Failed to create rider: {r.text}"
    return r.json()["rider_id"]


@pytest.fixture
def driver_id(client):
    """Create a fresh test driver (OFFLINE by default), return its ID."""
    r = client.post("/drivers", json={"name": "TestDriver", "vehicle_type": "UberX"})
    assert r.status_code == 201, f"Failed to create driver: {r.text}"
    did = r.json()["driver_id"]
    yield did
    with contextlib.suppress(Exception):
        client.post(
            f"/drivers/{did}/location",
            json={
                "lat": 0,
                "lng": 0,
                "status": "OFFLINE",
            },
        )


@pytest.fixture
def online_driver(client, known_pickup):
    """Create a driver and set them ONLINE near the pickup point."""
    r = client.post("/drivers", json={"name": "NearbyDriver", "vehicle_type": "UberX"})
    assert r.status_code == 201, f"Failed to create driver: {r.text}"
    driver_id = r.json()["driver_id"]

    loc_r = client.post(
        f"/drivers/{driver_id}/location",
        json={
            "lat": known_pickup["lat"] + 0.001,  # ~111m north
            "lng": known_pickup["lng"],
            "status": "ONLINE",
        },
    )
    assert loc_r.status_code == 200, f"Failed to set driver location: {loc_r.text}"
    yield driver_id
    with contextlib.suppress(Exception):
        client.post(
            f"/drivers/{driver_id}/location",
            json={
                "lat": 0,
                "lng": 0,
                "status": "OFFLINE",
            },
        )
