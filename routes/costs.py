"""
routes/costs.py
---------------
Blueprint handling all CRUD operations for cost records.

Endpoints:
  GET    /api/costs                  — list records (filter by vehicle_id)
  POST   /api/costs                  — create a record
  PUT    /api/costs/<id>             — update a record
  DELETE /api/costs/<id>             — delete a record
  POST   /api/costs/bulk-delete      — delete by vehicle_id + source
  GET    /api/costs/last-odometer    — most recent odometer for a vehicle
  GET    /api/categories             — list valid categories

Changelog:
  v1.0.0  GET / POST / DELETE
  v1.2.0  Added PUT; moved to blueprint
  v1.3.0  Categories from settings
  v1.4.0  vehicle_id field; GET vehicle filter
  v1.5.0  Fuel extra fields: litres, odometer, is_full_tank
  v1.6.0  last-odometer endpoint; odometer continuity warning; bulk-delete
  v1.7.0  Removed dead _get_categories(); single load_data() in odometer
           helpers; date normalised to ISO on POST/PUT; atomic writes via data.py
"""

from datetime import datetime

from flask import Blueprint, jsonify, request

from .data import load_data, make_id, parse_date_to_iso, save_data
from .settings import load_settings

costs_bp = Blueprint("costs", __name__)


@costs_bp.route("/costs", methods=["GET"])
def get_costs():
    """
    Return cost records as a JSON array.

    Query params:
      vehicle_id  — filter to one vehicle (omit for all)
      sort        — date (default) | amount | category
      order       — asc | desc
    """
    data       = load_data()
    vehicle_id = request.args.get("vehicle_id")
    sort_by    = request.args.get("sort", "date")
    order      = request.args.get("order", "")

    if vehicle_id:
        data = [c for c in data if c.get("vehicle_id") == vehicle_id]

    reverse = order == "desc" if order else sort_by == "date"

    if sort_by == "amount":
        data.sort(key=lambda c: float(c.get("amount", 0)), reverse=reverse)
    elif sort_by == "category":
        data.sort(key=lambda c: c.get("category", ""), reverse=reverse)
    else:
        data.sort(key=lambda c: parse_date_to_iso(c.get("date", "")), reverse=reverse)

    return jsonify(data)


@costs_bp.route("/costs", methods=["POST"])
def add_cost():
    """
    Create a new cost record.
    Returns HTTP 201 plus optional odometer_warning if reading goes backwards.
    """
    body = request.get_json(force=True, silent=True)
    if not body:
        return jsonify({"error": "Invalid or missing JSON body"}), 400

    vehicle_id = (body.get("vehicle_id") or "").strip()
    if not vehicle_id:
        return jsonify({"error": "vehicle_id is required"}), 400

    category = (body.get("category") or "").strip()
    if not category:
        return jsonify({"error": "category is required"}), 400

    try:
        amount = round(float(body["amount"]), 2)
        if amount < 0:
            raise ValueError
    except (KeyError, TypeError, ValueError):
        return jsonify({"error": "amount must be a non-negative number"}), 400

    raw_date = body.get("date", datetime.now().strftime("%Y-%m-%d"))
    entry = {
        "id":         make_id(),
        "vehicle_id": vehicle_id,
        "date":       parse_date_to_iso(raw_date),
        "category":   category,
        "amount":     amount,
        "note":       body.get("note", "").strip(),
        "source":     "manual",
    }

    odometer_warning = None

    # ── Fuel-specific fields ────────────────────────────────────────────────
    # Build the full entry FIRST, then persist once at the end. An earlier
    # version returned early inside the odometer branch, which skipped the
    # is_full_tank assignment below — so hand-entered fills silently lost their
    # full-tank flag and never produced an MPG figure (only imported rows did).
    # Order here is deliberate: every optional field is attached to `entry`
    # before the single load → append → save at the bottom.
    if category == "Fuel":
        litres = body.get("litres")
        if litres is not None:
            try:
                entry["litres"] = round(float(litres), 3)
            except (TypeError, ValueError):
                pass

        if "is_full_tank" in body:
            entry["is_full_tank"] = bool(body["is_full_tank"])

        odometer = body.get("odometer")
        if odometer is not None:
            try:
                entry["odometer"] = round(float(odometer), 1)
            except (TypeError, ValueError):
                pass

    # ── Persist (single load → append → save) ───────────────────────────────
    data = load_data()

    # Odometer continuity check needs the existing records, so it runs here
    # after the load. Fuel-only, and only when an odometer was supplied.
    if "odometer" in entry:
        last_odo = _last_odometer_from_records(data, vehicle_id)
        if last_odo is not None and entry["odometer"] < last_odo:
            odometer_warning = (
                f"Odometer {entry['odometer']:,.0f} is less than the previous "
                f"reading of {last_odo:,.0f} — please check it is correct."
            )

    data.append(entry)
    save_data(data)

    response = dict(entry)
    if odometer_warning:
        response["odometer_warning"] = odometer_warning
    return jsonify(response), 201


@costs_bp.route("/costs/<cost_id>", methods=["PUT"])
def update_cost(cost_id):
    """Partial update of a cost record by ID."""
    body = request.get_json(force=True, silent=True)
    if not body:
        return jsonify({"error": "Invalid or missing JSON body"}), 400

    data = load_data()
    for entry in data:
        if entry["id"] == cost_id:
            if "category" in body:
                cat = (body["category"] or "").strip()
                if not cat:
                    return jsonify({"error": "category cannot be empty"}), 400
                entry["category"] = cat
            if "amount" in body:
                try:
                    entry["amount"] = round(float(body["amount"]), 2)
                except (TypeError, ValueError):
                    return jsonify({"error": "amount must be a number"}), 400
            if "date" in body:
                entry["date"] = parse_date_to_iso(body["date"])
            if "note" in body:
                entry["note"] = body["note"].strip()
            if "litres" in body:
                try:
                    entry["litres"] = round(float(body["litres"]), 3) if body["litres"] not in (None, "") else None
                except (TypeError, ValueError):
                    pass
            if "odometer" in body:
                try:
                    entry["odometer"] = round(float(body["odometer"]), 1) if body["odometer"] not in (None, "") else None
                except (TypeError, ValueError):
                    pass
            if "is_full_tank" in body:
                entry["is_full_tank"] = bool(body["is_full_tank"])
            save_data(data)
            return jsonify(entry)

    return jsonify({"error": "Record not found"}), 404


@costs_bp.route("/costs/<cost_id>", methods=["DELETE"])
def delete_cost(cost_id):
    """Delete a cost record by ID. Idempotent."""
    data = load_data()
    save_data([c for c in data if c["id"] != cost_id])
    return jsonify({"ok": True})


@costs_bp.route("/costs/bulk-delete", methods=["POST"])
def bulk_delete():
    """Delete all records matching vehicle_id + source."""
    body       = request.get_json(force=True, silent=True) or {}
    vehicle_id = body.get("vehicle_id", "").strip()
    source     = body.get("source", "").strip()
    if not vehicle_id or not source:
        return jsonify({"error": "vehicle_id and source are required"}), 400
    data   = load_data()
    before = len(data)
    kept   = [c for c in data if not (c.get("vehicle_id") == vehicle_id and c.get("source") == source)]
    save_data(kept)
    return jsonify({"deleted": before - len(kept)})


@costs_bp.route("/costs/last-odometer", methods=["GET"])
def last_odometer():
    """Most recent odometer reading and date for a vehicle. Single file read."""
    vehicle_id = request.args.get("vehicle_id", "")
    if not vehicle_id:
        return jsonify({"error": "vehicle_id required"}), 400
    data = load_data()
    odo, odo_date = _last_odometer_with_date_from_records(data, vehicle_id)
    return jsonify({"odometer": odo, "date": odo_date})


@costs_bp.route("/categories", methods=["GET"])
def get_categories():
    """Return valid cost categories from settings."""
    return jsonify(load_settings()["categories"])


# ── Internal helpers ───────────────────────────────────────────────────────────

def _last_odometer_from_records(data: list, vehicle_id: str) -> float | None:
    """Return the highest odometer from an already-loaded records list."""
    readings = [
        float(c["odometer"])
        for c in data
        if c.get("vehicle_id") == vehicle_id
        and c.get("odometer") is not None
        and c.get("category") == "Fuel"
    ]
    return max(readings) if readings else None


def _last_odometer_with_date_from_records(data: list, vehicle_id: str):
    """Return (odometer, date) for the most recent fuel record with an odometer."""
    candidates = [
        c for c in data
        if c.get("vehicle_id") == vehicle_id
        and c.get("odometer") is not None
        and c.get("category") == "Fuel"
    ]
    if not candidates:
        return None, None
    candidates.sort(key=lambda c: parse_date_to_iso(c.get("date", "")), reverse=True)
    best = candidates[0]
    return float(best["odometer"]), best.get("date")
