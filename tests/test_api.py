"""
tests/test_api.py
-----------------
Endpoint-level tests via the Flask test client: cost CRUD + validation,
the odometer-continuity warning, vehicle validation + cascade delete,
settings validation, and a reports smoke test that exercises the full
load → aggregate → JSON path.
"""


# ── Costs: validation ──────────────────────────────────────────────────────────

def test_post_cost_requires_vehicle_id(client):
    resp = client.post("/api/costs", json={"category": "Fuel", "amount": 10})
    assert resp.status_code == 400


def test_post_cost_rejects_negative_amount(client, vehicle):
    resp = client.post("/api/costs", json={
        "vehicle_id": vehicle["id"], "category": "Fuel", "amount": -5,
    })
    assert resp.status_code == 400


def test_post_cost_rejects_non_numeric_amount(client, vehicle):
    resp = client.post("/api/costs", json={
        "vehicle_id": vehicle["id"], "category": "Fuel", "amount": "lots",
    })
    assert resp.status_code == 400


def test_post_cost_creates_record_with_iso_date(client, vehicle):
    resp = client.post("/api/costs", json={
        "vehicle_id": vehicle["id"], "category": "Fuel",
        "amount": 42.5, "date": "09/03/2024",  # UK format in
    })
    assert resp.status_code == 201
    body = resp.get_json()
    assert body["date"] == "2024-03-09"        # normalised to ISO out
    assert body["source"] == "manual"
    assert "id" in body


# ── Costs: odometer continuity warning ─────────────────────────────────────────

def test_odometer_warning_when_reading_goes_backwards(client, vehicle):
    vid = vehicle["id"]
    client.post("/api/costs", json={
        "vehicle_id": vid, "category": "Fuel", "amount": 60,
        "odometer": 5000, "date": "2024-01-01",
    })
    resp = client.post("/api/costs", json={
        "vehicle_id": vid, "category": "Fuel", "amount": 60,
        "odometer": 4000, "date": "2024-01-15",  # went backwards
    })
    assert resp.status_code == 201
    assert "odometer_warning" in resp.get_json()


def test_no_odometer_warning_when_increasing(client, vehicle):
    vid = vehicle["id"]
    client.post("/api/costs", json={
        "vehicle_id": vid, "category": "Fuel", "amount": 60,
        "odometer": 5000, "date": "2024-01-01",
    })
    resp = client.post("/api/costs", json={
        "vehicle_id": vid, "category": "Fuel", "amount": 60,
        "odometer": 5300, "date": "2024-01-15",
    })
    assert "odometer_warning" not in resp.get_json()


# ── Costs: list / update / delete ──────────────────────────────────────────────

def test_get_costs_filtered_by_vehicle(client, vehicle):
    other = client.post("/api/vehicles", json={"name": "Other"}).get_json()
    client.post("/api/costs", json={"vehicle_id": vehicle["id"],
                                    "category": "Fuel", "amount": 10})
    client.post("/api/costs", json={"vehicle_id": other["id"],
                                    "category": "Fuel", "amount": 20})
    resp = client.get(f"/api/costs?vehicle_id={vehicle['id']}")
    rows = resp.get_json()
    assert len(rows) == 1
    assert rows[0]["amount"] == 10


def test_update_and_delete_cost(client, vehicle):
    cid = client.post("/api/costs", json={
        "vehicle_id": vehicle["id"], "category": "Fuel", "amount": 10,
    }).get_json()["id"]

    upd = client.put(f"/api/costs/{cid}", json={"amount": 25})
    assert upd.get_json()["amount"] == 25.0

    assert client.delete(f"/api/costs/{cid}").status_code == 200
    # Deleting again is idempotent.
    assert client.delete(f"/api/costs/{cid}").status_code == 200


def test_update_missing_cost_returns_404(client):
    assert client.put("/api/costs/nope", json={"amount": 1}).status_code == 404


# ── Vehicles ───────────────────────────────────────────────────────────────────

def test_create_vehicle_requires_name(client):
    assert client.post("/api/vehicles", json={"make": "Ford"}).status_code == 400


def test_create_vehicle_rejects_implausible_year(client):
    assert client.post("/api/vehicles",
                       json={"name": "X", "year": 1700}).status_code == 400


def test_vehicle_registration_uppercased(client):
    v = client.post("/api/vehicles",
                    json={"name": "X", "registration": "ab12 cde"}).get_json()
    assert v["registration"] == "AB12 CDE"


def test_cascade_delete_removes_costs(client, vehicle):
    vid = vehicle["id"]
    client.post("/api/costs", json={"vehicle_id": vid, "category": "Fuel", "amount": 10})
    resp = client.delete(f"/api/vehicles/{vid}?cascade=true")
    assert resp.get_json()["costs_deleted"] == 1
    assert client.get(f"/api/costs?vehicle_id={vid}").get_json() == []


# ── Settings ───────────────────────────────────────────────────────────────────

def test_settings_defaults_on_first_run(client):
    body = client.get("/api/settings").get_json()
    assert body["currency_symbol"] == "£"
    assert "Fuel" in body["categories"]


def test_settings_partial_update_preserves_other_keys(client):
    client.post("/api/settings", json={"currency_symbol": "$"})
    body = client.get("/api/settings").get_json()
    assert body["currency_symbol"] == "$"
    assert "Fuel" in body["categories"]  # categories untouched


def test_settings_rejects_empty_categories(client):
    assert client.post("/api/settings", json={"categories": []}).status_code == 400


def test_settings_dedupes_and_strips_categories(client):
    client.post("/api/settings", json={"categories": [" Fuel ", "Fuel", "Tax", ""]})
    assert client.get("/api/settings").get_json()["categories"] == ["Fuel", "Tax"]


# ── Reports smoke ──────────────────────────────────────────────────────────────

def test_reports_summary_end_to_end(client, vehicle):
    vid = vehicle["id"]
    client.post("/api/costs", json={
        "vehicle_id": vid, "category": "Fuel", "amount": 60,
        "litres": 45, "odometer": 1000, "is_full_tank": True, "date": "2024-01-01",
    })
    client.post("/api/costs", json={
        "vehicle_id": vid, "category": "Fuel", "amount": 60,
        "litres": 45, "odometer": 1300, "is_full_tank": True, "date": "2024-01-15",
    })
    body = client.get(f"/api/reports/summary?vehicle_id={vid}").get_json()
    assert body["entry_count"] == 2
    assert body["total_spend"] == 120.0
    assert body["avg_mpg"] is not None  # one valid consecutive pair


def test_reports_require_vehicle_id(client):
    assert client.get("/api/reports/summary").status_code == 400


def test_monthly_report_zero_fills_range(client, vehicle):
    body = client.get(
        f"/api/reports/monthly?vehicle_id={vehicle['id']}&months=3"
    ).get_json()
    assert len(body["months"]) == 3  # every month present even with no data
