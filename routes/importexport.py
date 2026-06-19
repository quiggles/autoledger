"""
routes/importexport.py
-----------------------
Blueprint handling all import and export operations.

Endpoints:
  GET  /api/export/json          — export all vehicles + records as AutoLedger JSON
  POST /api/import/json          — import from AutoLedger JSON
  POST /api/import/lubelogger    — import from a LubeLogger CSV export

LubeLogger CSV mapping
-----------------------
LubeLogger exports one CSV per tab. We detect the tab type from the
column headers, then map each row to an AutoLedger category:

  Fuel tab      → "Fuel"
  Taxes tab     → "Tax & Registration"
  Service tab   → "Insurance" (if description contains insurance keywords)
               → "Servicing & Repairs" (all other service records)

The vehicle_id to assign imported records to is passed as a form field.

Changelog:
  v1.1.0  Initial import/export implementation
  v1.2.0  Moved to blueprint; full comments; narrowed error handling
  v1.4.0  Export includes vehicles; import handles vehicle_id;
           LubeLogger import accepts vehicle_id form field
"""

import csv
import io
import json
import logging
from datetime import datetime

from flask import Blueprint, Response, jsonify, request

from version import __version__

from .data import load_data, load_vehicles, make_id, parse_date_to_iso, save_data, save_vehicles
from .logging_config import log_event

io_bp = Blueprint("importexport", __name__)

# ── LubeLogger helpers ────────────────────────────────────────────────────────

_INSURANCE_KEYWORDS = ("insurance", "insur", "premium", "policy", "cover")


def _detect_lubelogger_type(headers) -> str:
    """
    Infer which LubeLogger tab a CSV came from by inspecting column headers.
    Returns one of: 'fuel' | 'service' | 'tax'
    """
    h = {c.lower().strip() for c in headers}
    # Fuel tab: has a fuel volume column (actual export uses "fuelconsumed")
    if h & {"fuelconsumed", "gallons", "liters", "litres",
            "consumption(l)", "consumption", "quantity", "qty"}:
        return "fuel"
    # Service/Repair tabs have a description column
    if "description" in h:
        return "service"
    return "tax"


def _map_lubelogger_row(row: dict, record_type: str, vehicle_id: str) -> dict:
    """
    Convert a single LubeLogger CSV row into an AutoLedger record dict.

    Actual LubeLogger CSV columns (confirmed from export):
      Date, Odometer, FuelConsumed, Cost, FuelEconomy,
      IsFillToFull, MissedFuelUp, Notes, Tags

    Parameters
    ----------
    row         : dict from csv.DictReader (raw strings)
    record_type : one of 'fuel' | 'service' | 'tax'
    vehicle_id  : ID of the vehicle to attach this record to
    """
    # Normalise keys: lowercase and strip whitespace
    h = {k.lower().strip(): v.strip() for k, v in row.items()}

    def _clean_num(s):
        """Strip currency symbols and commas, return clean string for float()."""
        return s.replace("£","").replace("$","").replace("€","").replace(",","").strip()

    # ── Date ──────────────────────────────────────────────────────────────────
    raw_date = (
        h.get("date") or h.get("date refueled") or h.get("fuelup_date", "")
    )
    if not raw_date:
        d = h.get("day",   "1").zfill(2)
        m = h.get("month", "1").zfill(2)
        y = h.get("year",  str(datetime.now().year))
        raw_date = f"{y}-{m}-{d}"
    date = parse_date_to_iso(raw_date)

    # ── Cost / Amount ─────────────────────────────────────────────────────────
    raw_cost = (
        h.get("cost") or h.get("total cost") or h.get("totalcost")
        or h.get("total price") or "0"
    )
    try:
        amount = round(float(_clean_num(raw_cost)), 2)
    except ValueError:
        amount = 0.0

    # ── Note ──────────────────────────────────────────────────────────────────
    note = h.get("notes") or h.get("note") or h.get("description") or ""

    # ── Category ──────────────────────────────────────────────────────────────
    if record_type == "fuel":
        category = "Fuel"
    elif record_type == "tax":
        category = "Tax & Registration"
    else:
        desc_lower = note.lower()
        category = "Insurance" if any(kw in desc_lower for kw in _INSURANCE_KEYWORDS) \
                   else "Servicing & Repairs"

    entry = {
        "id":         make_id(),
        "vehicle_id": vehicle_id,
        "date":       date,
        "category":   category,
        "amount":     amount,
        "note":       note,
        "source":     "lubelogger",
    }

    # ── Fuel-specific fields ───────────────────────────────────────────────────
    if record_type == "fuel":

        # Litres consumed — "FuelConsumed" in LubeLogger exports
        raw_litres = (
            h.get("fuelconsumed") or h.get("consumption(l)") or
            h.get("consumption") or h.get("liters") or
            h.get("litres") or h.get("quantity") or ""
        )
        litres = None
        if raw_litres:
            try:
                litres = round(float(_clean_num(raw_litres)), 3)
                entry["litres"] = litres
            except ValueError:
                pass

        # Odometer reading — "Odometer" in LubeLogger exports
        raw_odo = (
            h.get("odometer") or h.get("odometer(mi.)") or
            h.get("odometer(km.)") or h.get("mileage") or ""
        )
        if raw_odo:
            try:
                entry["odometer"] = round(float(_clean_num(raw_odo)), 1)
            except ValueError:
                pass

        # Full tank flag — "IsFillToFull" in LubeLogger exports
        raw_full = (
            h.get("isfilltofull") or h.get("is full to tank") or
            h.get("full tank") or h.get("is_full_tank") or ""
        )
        entry["is_full_tank"] = raw_full.lower() in ("true", "1", "yes", "y", "✓", "x")

        # Unit cost — calculated from cost/litres since LubeLogger doesn't export it
        if litres and litres > 0 and amount > 0:
            entry["unit_cost"] = round(amount / litres, 4)

        # Fuel economy — LubeLogger stores L/100mi as "FuelEconomy"
        raw_economy = h.get("fueleconomy") or h.get("fuel economy") or ""
        if raw_economy:
            try:
                fe = float(_clean_num(raw_economy))
                if fe > 0:
                    entry["fuel_economy"] = round(fe, 4)
            except ValueError:
                pass

    return entry


# ── Export: AutoLedger JSON ───────────────────────────────────────────────────

@io_bp.route("/export/json", methods=["GET"])
def export_json():
    """
    Export all vehicles and all cost records as a single downloadable
    AutoLedger JSON file.

    The envelope includes metadata (version, export timestamp, app name)
    so the file is self-describing and can be validated on re-import.
    Vehicle records are included so a full restore is possible from one file.
    """
    costs    = load_data()
    vehicles = load_vehicles()
    payload  = {
        "app":          "AutoLedger",
        "version":      __version__,
        "exported_at":  datetime.now().isoformat(),
        "vehicle_count": len(vehicles),
        "record_count": len(costs),
        "vehicles":     vehicles,
        "records":      costs,
    }
    filename = f"autoledger-export-{datetime.now().strftime('%Y%m%d')}.json"
    return Response(
        json.dumps(payload, indent=2),
        mimetype="application/json",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )


# ── Import: AutoLedger JSON ───────────────────────────────────────────────────

@io_bp.route("/import/json", methods=["POST"])
def import_json():
    """
    Import vehicles and records from a previously exported AutoLedger JSON file.

    Vehicles are merged by ID — existing vehicles are not overwritten.
    Cost records are merged by ID — duplicates are skipped.

    Accepts both the v1.4.0 envelope format (with 'vehicles' and 'records'
    keys) and the legacy format (bare array of records, or envelope with
    only 'records') for backwards compatibility.
    """
    file = request.files.get("file")
    if not file:
        return jsonify({"error": "No file uploaded"}), 400

    try:
        payload = json.load(file)
    except Exception as e:
        return jsonify({"error": f"JSON parse error: {e}"}), 400

    # ── Extract vehicles and records from payload ──────────────────────────────
    if isinstance(payload, dict):
        records  = payload.get("records", [])
        v_import = payload.get("vehicles", [])
    elif isinstance(payload, list):
        records  = payload      # legacy bare-array format
        v_import = []
    else:
        return jsonify({"error": "Unrecognised format — expected object or array"}), 400

    # ── Merge vehicles ────────────────────────────────────────────────────────
    existing_vehicles    = load_vehicles()
    existing_vehicle_ids = {v["id"] for v in existing_vehicles}
    vehicles_imported    = 0

    for v in v_import:
        if v.get("id") and v["id"] not in existing_vehicle_ids:
            existing_vehicles.append(v)
            existing_vehicle_ids.add(v["id"])
            vehicles_imported += 1

    if vehicles_imported:
        save_vehicles(existing_vehicles)

    # ── Merge cost records ────────────────────────────────────────────────────
    # Each row is converted defensively. Previously a single record with a
    # non-numeric `amount` raised inside `float(...)` and aborted the WHOLE
    # import — losing every subsequent row. We now mirror the LubeLogger path:
    # skip the bad row, collect a human-readable error, and import the rest.
    data        = load_data()
    existing_ids = {c["id"] for c in data}
    imported    = 0
    skipped     = 0
    errors      = []

    for i, r in enumerate(records):
        rec_id = r.get("id")
        if rec_id and rec_id in existing_ids:
            skipped += 1
            continue
        try:
            amount = float(r.get("amount", 0))
        except (TypeError, ValueError):
            errors.append(f"Record {i + 1}: invalid amount {r.get('amount')!r} — skipped")
            log_event(
                "import_row_skipped",
                level=logging.WARNING,
                index=i + 1,
                reason="invalid_amount",
                value=r.get("amount"),
            )
            continue
        entry = {
            "id":         rec_id or make_id(),
            "vehicle_id": r.get("vehicle_id", ""),
            "date":       parse_date_to_iso(r.get("date", "")),
            "category":   r.get("category", "Fuel"),
            "amount":     round(amount, 2),
            "note":       r.get("note", ""),
            "source":     r.get("source", "import"),
        }
        # Preserve fuel-specific fields so a re-import keeps MPG-relevant data.
        for fld in ("litres", "odometer", "is_full_tank", "unit_cost", "fuel_economy"):
            if fld in r:
                entry[fld] = r[fld]
        data.append(entry)
        existing_ids.add(entry["id"])
        imported += 1

    save_data(data)
    return jsonify({
        "imported":          imported,
        "skipped":           skipped,
        "vehicles_imported": vehicles_imported,
        "errors":            errors,
    })


# ── Import: LubeLogger CSV ────────────────────────────────────────────────────

@io_bp.route("/import/lubelogger", methods=["POST"])
def import_lubelogger():
    """
    Import records from a single-tab LubeLogger CSV export.

    Requires a vehicle_id form field — records are attached to that vehicle.
    The tab type (fuel / service / tax) is auto-detected from column headers.
    Each row is mapped individually so a single bad row does not abort the
    entire import — errors are collected and returned.
    """
    file       = request.files.get("file")
    vehicle_id = (request.form.get("vehicle_id") or "").strip()

    if not file:
        return jsonify({"error": "No file uploaded"}), 400
    if not vehicle_id:
        return jsonify({"error": "vehicle_id is required"}), 400

    # ── Parse CSV ─────────────────────────────────────────────────────────────
    try:
        content = file.read().decode("utf-8-sig")   # strip BOM from Windows exports
        reader  = csv.DictReader(io.StringIO(content))
        rows    = list(reader)
    except Exception as e:
        return jsonify({"error": f"CSV parse error: {e}"}), 400

    if not rows:
        return jsonify({"error": "CSV file is empty or has no data rows"}), 400

    record_type = _detect_lubelogger_type(rows[0].keys())
    data        = load_data()
    imported    = 0
    errors      = []

    for i, row in enumerate(rows):
        try:
            entry = _map_lubelogger_row(row, record_type, vehicle_id)
            data.append(entry)
            imported += 1
        except Exception as e:
            errors.append(f"Row {i + 2}: {e}")

    save_data(data)
    type_label = {"fuel": "Fuel", "service": "Service/Repair", "tax": "Tax"}[record_type]

    return jsonify({
        "imported":      imported,
        "detected_type": type_label,
        "errors":        errors,
    })
