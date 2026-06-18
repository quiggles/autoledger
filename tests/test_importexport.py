"""
tests/test_importexport.py
--------------------------
Tests for LubeLogger CSV detection/mapping and the AutoLedger JSON
export/import round-trip (including ID-based de-duplication).
"""

import io
import json

from routes.importexport import _detect_lubelogger_type, _map_lubelogger_row

# ── Tab-type detection ─────────────────────────────────────────────────────────

def test_detect_fuel_tab_from_fuelconsumed_header():
    headers = ["Date", "Odometer", "FuelConsumed", "Cost", "IsFillToFull"]
    assert _detect_lubelogger_type(headers) == "fuel"


def test_detect_service_tab_from_description_header():
    headers = ["Date", "Odometer", "Description", "Cost"]
    assert _detect_lubelogger_type(headers) == "service"


def test_detect_tax_tab_as_fallback():
    headers = ["Date", "Cost"]
    assert _detect_lubelogger_type(headers) == "tax"


# ── Row mapping ────────────────────────────────────────────────────────────────

def test_map_fuel_row_full_mapping():
    row = {
        "Date": "09/03/2024",          # UK DD/MM/YYYY
        "Odometer": "54321",
        "FuelConsumed": "48.12",
        "Cost": "£62.55",              # currency symbol must be stripped
        "IsFillToFull": "True",
        "FuelEconomy": "14.9",
        "Notes": "BP Example Forecourt",
    }
    entry = _map_lubelogger_row(row, "fuel", vehicle_id="v1")
    assert entry["category"] == "Fuel"
    assert entry["date"] == "2024-03-09"
    assert entry["odometer"] == 54321.0
    assert entry["litres"] == 48.12
    assert entry["amount"] == 62.55
    assert entry["is_full_tank"] is True
    assert entry["source"] == "lubelogger"
    assert entry["vehicle_id"] == "v1"
    # unit_cost derived from cost / litres
    assert entry["unit_cost"] == round(62.55 / 48.12, 4)


def test_map_service_row_detects_insurance_by_keyword():
    row = {"Date": "01/04/2024", "Description": "Annual insurance premium", "Cost": "450"}
    entry = _map_lubelogger_row(row, "service", vehicle_id="v1")
    assert entry["category"] == "Insurance"


def test_map_service_row_defaults_to_servicing():
    row = {"Date": "01/04/2024", "Description": "New brake pads", "Cost": "180"}
    entry = _map_lubelogger_row(row, "service", vehicle_id="v1")
    assert entry["category"] == "Servicing & Repairs"


def test_map_row_with_bad_cost_defaults_to_zero():
    row = {"Date": "01/04/2024", "Cost": "n/a", "Description": "mystery"}
    entry = _map_lubelogger_row(row, "service", vehicle_id="v1")
    assert entry["amount"] == 0.0


# ── CSV import endpoint ────────────────────────────────────────────────────────

def test_lubelogger_csv_import_endpoint(client, vehicle):
    csv_text = (
        "Date,Odometer,FuelConsumed,Cost,IsFillToFull,Notes\n"
        "01/01/2024,1000,45.0,60.00,True,First fill\n"
        "15/01/2024,1300,45.0,61.00,True,Second fill\n"
    )
    data = {
        "vehicle_id": vehicle["id"],
        "file": (io.BytesIO(csv_text.encode("utf-8")), "fuel.csv"),
    }
    resp = client.post("/api/import/lubelogger", data=data,
                       content_type="multipart/form-data")
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["imported"] == 2
    assert body["detected_type"] == "Fuel"
    assert body["errors"] == []


def test_lubelogger_import_requires_vehicle_id(client):
    data = {"file": (io.BytesIO(b"Date,Cost\n01/01/2024,10\n"), "x.csv")}
    resp = client.post("/api/import/lubelogger", data=data,
                       content_type="multipart/form-data")
    assert resp.status_code == 400


# ── JSON export / import round-trip ────────────────────────────────────────────

def test_json_export_import_round_trip(client, vehicle):
    # Seed one cost record.
    client.post("/api/costs", json={
        "vehicle_id": vehicle["id"], "category": "Fuel", "amount": 50, "date": "2024-01-01",
    })

    export = client.get("/api/export/json")
    assert export.status_code == 200
    payload = json.loads(export.data)
    assert payload["record_count"] == 1
    assert payload["vehicle_count"] == 1

    # Re-importing the same file must skip everything (ID de-dup).
    reimport = client.post(
        "/api/import/json",
        data={"file": (io.BytesIO(export.data), "backup.json")},
        content_type="multipart/form-data",
    )
    body = reimport.get_json()
    assert body["imported"] == 0
    assert body["skipped"] == 1
    assert body["vehicles_imported"] == 0


def test_json_import_legacy_bare_array(client, vehicle):
    records = [{"id": "abc", "vehicle_id": vehicle["id"],
                "category": "Fuel", "amount": 30, "date": "2024-02-02"}]
    resp = client.post(
        "/api/import/json",
        data={"file": (io.BytesIO(json.dumps(records).encode()), "legacy.json")},
        content_type="multipart/form-data",
    )
    assert resp.get_json()["imported"] == 1
