"""Starter test — verify /healthz returns 200 when DB is reachable."""

import pytest


@pytest.mark.asyncio
async def test_healthz_ok(client):
    """GET /healthz returns 200 with status=ok and db=connected."""
    response = await client.get("/healthz")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"
    assert data["db"] == "connected"
