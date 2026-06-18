"""
routes/settings.py
------------------
Blueprint handling user settings: currency symbol and custom categories.

Settings are persisted to /data/settings.json alongside costs.json so
they survive container restarts and are portable with the data volume.

Endpoints:
  GET  /api/settings              — retrieve current settings
  POST /api/settings              — save updated settings

Default settings (applied on first run):
  currency_symbol : "£"
  categories      : ["Fuel", "Insurance", "Servicing & Repairs",
                     "Tax & Registration"]

Changelog:
  v1.3.0  Initial — currency symbol and category management
"""

from flask import Blueprint, jsonify, request

# Settings live in the same volume as the cost data; reuse the shared atomic I/O.
from .data import SETTINGS_FILE, _load_json, _save_json

settings_bp = Blueprint("settings", __name__)

# ── Defaults ──────────────────────────────────────────────────────────────────

DEFAULT_SETTINGS = {
    "currency_symbol": "£",
    "categories": [
        "Fuel",
        "Insurance",
        "Servicing & Repairs",
        "Tax & Registration",
    ],
}


# ── Helpers ───────────────────────────────────────────────────────────────────

def load_settings() -> dict:
    """
    Load settings from disk, falling back to defaults for any missing keys.
    Forward-compatible — new keys in future versions get their default values.
    """
    try:
        stored = _load_json(SETTINGS_FILE)
        if not isinstance(stored, dict):
            return dict(DEFAULT_SETTINGS)
        return {**DEFAULT_SETTINGS, **stored}
    except Exception:
        return dict(DEFAULT_SETTINGS)


def save_settings(settings: dict) -> None:
    """Atomically persist settings to disk via shared _save_json."""
    _save_json(SETTINGS_FILE, settings)


# ── Routes ────────────────────────────────────────────────────────────────────

@settings_bp.route("/settings", methods=["GET"])
def get_settings():
    """
    Return the current settings object.
    Returns exactly what is saved in settings.json — does NOT auto-merge
    categories from cost records, as that would re-add deliberately deleted
    categories every time the page loads.
    """
    return jsonify(load_settings())


@settings_bp.route("/settings", methods=["POST"])
def save_settings_route():
    """
    Update settings. Accepts a partial body — only supplied keys are updated,
    so the client doesn't need to send the full object to change one field.

    Validation:
      currency_symbol  must be a non-empty string (max 4 chars)
      categories       must be a list of at least 1 non-empty strings
    """
    body = request.get_json(force=True, silent=True)
    if not body:
        return jsonify({"error": "Invalid or missing JSON body"}), 400

    current = load_settings()

    # ── Validate and apply currency_symbol ────────────────────────────────────
    if "currency_symbol" in body:
        sym = body["currency_symbol"]
        if not isinstance(sym, str) or not sym.strip():
            return jsonify({"error": "currency_symbol must be a non-empty string"}), 400
        current["currency_symbol"] = sym.strip()[:4]  # cap at 4 chars

    # ── Validate and apply categories ─────────────────────────────────────────
    if "categories" in body:
        cats = body["categories"]
        if not isinstance(cats, list) or len(cats) == 0:
            return jsonify({"error": "categories must be a non-empty list"}), 400
        # Filter out blanks, deduplicate, preserve order
        cleaned = list(dict.fromkeys(
            c.strip() for c in cats if isinstance(c, str) and c.strip()
        ))
        if not cleaned:
            return jsonify({"error": "No valid category names provided"}), 400
        current["categories"] = cleaned

    save_settings(current)
    return jsonify(current)
