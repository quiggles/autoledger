"""
tests/test_robustness.py
------------------------
Guards for the v2.0.0 robustness work: a single malformed record must not 500 a
whole report, and a bad row must not abort a whole JSON import.
"""

import io
import json

from routes import data as data_module


def _write_costs(records):
    """Write raw cost records straight to the store, bypassing validation, so we
    can plant a deliberately malformed record the API would normally reject."""
    data_module.save_data(records)


# ── Reports survive a malformed amount ─────────────────────────────────────────

def test_reports_skip_bad_amount_instead_of_500(client, vehicle):
    vid = vehicle["id"]
    _write_costs([
        {"id": "good", "vehicle_id": vid, "category": "Fuel",
         "amount": 50.0, "date": "2024-01-01"},
        {"id": "bad", "vehicle_id": vid, "category": "Fuel",
         "amount": "not-a-number", "date": "2024-01-02"},
    ])

    # Every aggregation endpoint must return 200, counting only the good record.
    summary = client.get(f"/api/reports/summary?vehicle_id={vid}")
    assert summary.status_code == 200
    assert summary.get_json()["total_spend"] == 50.0

    for path in ("monthly", "category", "cumulative", "annual",
                 "fuelvsother", "costpermile", "fillinterval", "efficiency"):
        resp = client.get(f"/api/reports/{path}?vehicle_id={vid}")
        assert resp.status_code == 200, f"{path} 500'd on a bad record"


# ── JSON import skips a bad row instead of aborting ────────────────────────────

def test_json_import_skips_bad_row_and_imports_rest(client, vehicle):
    payload = {
        "records": [
            {"id": "r1", "vehicle_id": vehicle["id"], "category": "Fuel",
             "amount": 30, "date": "2024-01-01"},
            {"id": "r2", "vehicle_id": vehicle["id"], "category": "Fuel",
             "amount": "oops", "date": "2024-01-02"},
            {"id": "r3", "vehicle_id": vehicle["id"], "category": "Fuel",
             "amount": 45, "date": "2024-01-03"},
        ]
    }
    resp = client.post(
        "/api/import/json",
        data={"file": (io.BytesIO(json.dumps(payload).encode()), "x.json")},
        content_type="multipart/form-data",
    )
    body = resp.get_json()
    assert body["imported"] == 2          # r1 and r3
    assert len(body["errors"]) == 1       # r2 reported, not fatal
    assert "amount" in body["errors"][0]


# ── Configurable MPG bounds are honoured ───────────────────────────────────────

def test_mpg_bounds_from_settings_widen_acceptance(client, vehicle):
    """A ~120 MPG reading is dropped by the default 100 ceiling but kept once the
    ceiling is raised — proving the bound is read from settings, not hardcoded."""
    vid = vehicle["id"]
    # Two full-tank fills 600 miles apart on ~22.7 L → ~120 MPG.
    _write_costs([
        {"id": "f1", "vehicle_id": vid, "category": "Fuel", "amount": 30,
         "date": "2024-01-01", "litres": 22.73, "odometer": 1000, "is_full_tank": True},
        {"id": "f2", "vehicle_id": vid, "category": "Fuel", "amount": 30,
         "date": "2024-01-15", "litres": 22.73, "odometer": 1600, "is_full_tank": True},
    ])

    eff_default = client.get(f"/api/reports/efficiency?vehicle_id={vid}").get_json()
    assert eff_default[1]["mpg"] is None    # 120 MPG clipped by default max 100

    client.post("/api/settings", json={"mpg_max": 200})
    eff_wide = client.get(f"/api/reports/efficiency?vehicle_id={vid}").get_json()
    assert eff_wide[1]["mpg"] is not None and eff_wide[1]["mpg"] > 100
