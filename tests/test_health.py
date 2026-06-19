"""
tests/test_health.py
--------------------
Tests for the unauthenticated health endpoint.
"""

from version import __version__


def test_health_is_public(anon_client):
    """Health must work with no account and no session (monitors poll it)."""
    resp = anon_client.get("/api/health")
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["status"] == "ok"
    assert body["version"] == __version__
    assert body["vehicles"] == 0
    assert body["records"] == 0


def test_health_counts_reflect_data(client, vehicle):
    client.post("/api/costs", json={
        "vehicle_id": vehicle["id"], "category": "Fuel", "amount": 40, "date": "2024-01-01",
    })
    body = client.get("/api/health").get_json()
    assert body["vehicles"] == 1
    assert body["records"] == 1
