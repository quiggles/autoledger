"""
tests/test_public.py
--------------------
Tests for the unauthenticated aggregate-stats endpoint that feeds the Homepage
dashboard tile (``GET /api/public/stats``).

These assert both the security contract (reachable with no session, exposes only
coarse aggregates) and the numbers (YTD spend window, entry/vehicle counts, and
the due-reminder count).
"""

from datetime import date


def test_public_stats_is_public_and_zeroed_on_empty(anon_client):
    """Must work with no account and no session, returning zeroes on empty data."""
    resp = anon_client.get("/api/public/stats")
    assert resp.status_code == 200
    body = resp.get_json()
    assert body == {
        "vehicles": 0,
        "entries": 0,
        "ytd_spend": 0.0,
        "reminders_due": 0,
    }


def test_public_stats_counts_and_ytd_spend(client, vehicle):
    """
    Entries/vehicles reflect stored data, and ytd_spend sums only records dated
    in the current calendar year — a prior-year record is excluded.
    """
    this_year = date.today().year
    # Two in-year costs (should sum) and one from a previous year (excluded).
    client.post("/api/costs", json={
        "vehicle_id": vehicle["id"], "category": "Fuel",
        "amount": 40.00, "date": f"{this_year}-01-05",
    })
    client.post("/api/costs", json={
        "vehicle_id": vehicle["id"], "category": "Service",
        "amount": 60.50, "date": f"{this_year}-03-11",
    })
    client.post("/api/costs", json={
        "vehicle_id": vehicle["id"], "category": "Fuel",
        "amount": 99.99, "date": f"{this_year - 1}-12-30",
    })

    body = client.get("/api/public/stats").get_json()
    assert body["vehicles"] == 1
    assert body["entries"] == 3          # all records counted
    assert body["ytd_spend"] == 100.50   # only the two in-year records
    assert body["reminders_due"] == 0


def test_public_stats_bad_amount_does_not_crash(client, vehicle):
    """A malformed amount is skipped, not 500'd — one rogue row can't break the tile."""
    this_year = date.today().year
    client.post("/api/costs", json={
        "vehicle_id": vehicle["id"], "category": "Fuel",
        "amount": 25.00, "date": f"{this_year}-02-02",
    })
    # Force a malformed amount straight into storage (bypassing validation) to
    # simulate a bad import, then confirm the endpoint still returns cleanly.
    from routes.data import load_data, save_data
    rows = load_data()
    rows.append({
        "id": "bad", "vehicle_id": vehicle["id"], "category": "Fuel",
        "amount": "n/a", "date": f"{this_year}-02-03",
    })
    save_data(rows)

    resp = client.get("/api/public/stats")
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["entries"] == 2          # the bad row is still an entry
    assert body["ytd_spend"] == 25.00    # but its amount is skipped from the sum


def test_public_stats_counts_due_reminders(client, vehicle):
    """A reminder whose due date is in the past counts as due/overdue."""
    client.post("/api/reminders", json={
        "vehicle_id": vehicle["id"], "type": "MOT",
        "due_date": "2000-01-01",   # long overdue
    })
    body = client.get("/api/public/stats").get_json()
    assert body["reminders_due"] == 1
