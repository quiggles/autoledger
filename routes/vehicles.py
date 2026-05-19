"""
routes/vehicles.py
------------------
Blueprint handling all CRUD operations for vehicles.

A vehicle record represents a car being tracked. Every cost record
references a vehicle_id so costs are always scoped to one vehicle.

Vehicle fields:
  id           — UUID4 (generated on creation)
  name         — user-defined nickname, e.g. "Daily Driver"
  make         — manufacturer, e.g. "Toyota"
  model        — model name, e.g. "Yaris"
  year         — integer year, e.g. 2019
  colour       — colour string, e.g. "Midnight Blue"
  registration — registration plate, e.g. "AB12 CDE"
  created_at   — ISO-8601 timestamp

Endpoints:
  GET    /api/vehicles          — list all vehicles
  POST   /api/vehicles          — create a vehicle
  PUT    /api/vehicles/<id>     — update a vehicle
  DELETE /api/vehicles/<id>     — delete a vehicle (and optionally its costs)

Changelog:
  v1.4.0  Initial — full CRUD; cascade delete option
"""

from flask import Blueprint, request, jsonify
from datetime import datetime
from .data import load_data, save_data, make_id, load_vehicles, save_vehicles

vehicles_bp = Blueprint("vehicles", __name__)


# ── GET /api/vehicles ──────────────────────────────────────────────────────────

@vehicles_bp.route("/vehicles", methods=["GET"])
def get_vehicles():
    """Return all vehicles as a JSON array, ordered by creation date."""
    vehicles = load_vehicles()
    vehicles.sort(key=lambda v: v.get("created_at", ""))
    return jsonify(vehicles)


# ── POST /api/vehicles ─────────────────────────────────────────────────────────

@vehicles_bp.route("/vehicles", methods=["POST"])
def add_vehicle():
    """
    Create a new vehicle.

    Expected JSON body (name is required; all other fields optional):
      {
        "name":         str,   required
        "make":         str,   optional
        "model":        str,   optional
        "year":         int,   optional
        "colour":       str,   optional
        "registration": str    optional
      }

    Returns the created vehicle with HTTP 201.
    """
    body = request.get_json(force=True, silent=True)
    if not body:
        return jsonify({"error": "Invalid or missing JSON body"}), 400

    name = (body.get("name") or "").strip()
    if not name:
        return jsonify({"error": "name is required"}), 400

    # Validate year if provided
    year = body.get("year")
    if year is not None:
        try:
            year = int(year)
            if year < 1886 or year > datetime.now().year + 2:
                raise ValueError
        except (TypeError, ValueError):
            return jsonify({"error": "year must be a valid 4-digit year"}), 400

    vehicle = {
        "id":           make_id(),
        "name":         name,
        "make":         (body.get("make")         or "").strip(),
        "model":        (body.get("model")        or "").strip(),
        "year":         year,
        "colour":       (body.get("colour")       or "").strip(),
        "registration": (body.get("registration") or "").strip().upper(),
        "notes":        (body.get("notes")        or "").strip(),
        "created_at":   datetime.now().isoformat(),
    }

    vehicles = load_vehicles()
    vehicles.append(vehicle)
    save_vehicles(vehicles)
    return jsonify(vehicle), 201


# ── PUT /api/vehicles/<id> ─────────────────────────────────────────────────────

@vehicles_bp.route("/vehicles/<vehicle_id>", methods=["PUT"])
def update_vehicle(vehicle_id):
    """
    Update an existing vehicle by ID.
    Accepts a partial body — only supplied fields are updated.
    Returns the updated vehicle, or 404 if not found.
    """
    body = request.get_json(force=True, silent=True)
    if not body:
        return jsonify({"error": "Invalid or missing JSON body"}), 400

    vehicles = load_vehicles()
    for v in vehicles:
        if v["id"] == vehicle_id:
            if "name" in body:
                name = body["name"].strip()
                if not name:
                    return jsonify({"error": "name cannot be empty"}), 400
                v["name"] = name
            if "make"         in body: v["make"]         = (body["make"]         or "").strip()
            if "model"        in body: v["model"]        = (body["model"]        or "").strip()
            if "colour"       in body: v["colour"]       = (body["colour"]       or "").strip()
            if "registration" in body: v["registration"] = (body["registration"] or "").strip().upper()
            if "notes"        in body: v["notes"]        = (body["notes"]        or "").strip()
            if "year"         in body:
                year = body["year"]
                if year is not None:
                    try:
                        year = int(year)
                    except (TypeError, ValueError):
                        return jsonify({"error": "year must be a number"}), 400
                v["year"] = year
            save_vehicles(vehicles)
            return jsonify(v)

    return jsonify({"error": "Vehicle not found"}), 404


# ── DELETE /api/vehicles/<id> ──────────────────────────────────────────────────

@vehicles_bp.route("/vehicles/<vehicle_id>", methods=["DELETE"])
def delete_vehicle(vehicle_id):
    """
    Delete a vehicle by ID.

    Query param:
      cascade=true  — also delete all cost records belonging to this vehicle.
                      If omitted or false, costs are orphaned (vehicle_id kept
                      but vehicle no longer exists) which is safe — they just
                      won't appear in any vehicle-filtered view.

    Returns { "ok": true, "costs_deleted": int }.
    """
    vehicles = load_vehicles()
    vehicles = [v for v in vehicles if v["id"] != vehicle_id]
    save_vehicles(vehicles)

    # Optionally cascade-delete associated cost records
    costs_deleted = 0
    if request.args.get("cascade", "").lower() == "true":
        all_costs = load_data()
        kept      = [c for c in all_costs if c.get("vehicle_id") != vehicle_id]
        costs_deleted = len(all_costs) - len(kept)
        save_data(kept)

    return jsonify({"ok": True, "costs_deleted": costs_deleted})
