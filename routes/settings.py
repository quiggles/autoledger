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
  mpg_min         : 10    — efficiency readings below this are discarded as noise
  mpg_max         : 100   — efficiency readings above this are discarded as noise

Changelog:
  v1.3.0  Initial — currency symbol and category management
  v2.0.0  Configurable MPG sanity bounds (mpg_min / mpg_max) so very efficient
           or very thirsty vehicles are no longer silently clipped by hardcoded
           10–100 limits.
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
    # MPG sanity bounds. A reading outside [mpg_min, mpg_max] is treated as a bad
    # odometer entry or a missed fill and dropped from efficiency stats. These
    # were hardcoded to 10/100 in reports.py; exposing them lets owners of very
    # efficient (EV-range hybrid) or very thirsty (heavy tow) vehicles keep
    # legitimate readings. See reports.py:_mpg_bounds().
    "mpg_min": 10,
    "mpg_max": 100,
    # Daily time (HH:MM, 24h) at which the in-process scheduler evaluates
    # reminders and sends notifications. Human-readable in the UI; stored as a
    # simple HH:MM string. Changing it reschedules the job live (see scheduler).
    "reminder_check_time": "08:00",
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

    # ── Validate and apply MPG sanity bounds ──────────────────────────────────
    # Both are optional in the body; each is validated independently, then the
    # pair is checked for ordering so min < max always holds.
    if "mpg_min" in body or "mpg_max" in body:
        try:
            new_min = float(body.get("mpg_min", current["mpg_min"]))
            new_max = float(body.get("mpg_max", current["mpg_max"]))
        except (TypeError, ValueError):
            return jsonify({"error": "mpg_min and mpg_max must be numbers"}), 400
        if new_min < 0 or new_max <= 0:
            return jsonify({"error": "MPG bounds must be positive"}), 400
        if new_min >= new_max:
            return jsonify({"error": "mpg_min must be less than mpg_max"}), 400
        current["mpg_min"] = round(new_min, 1)
        current["mpg_max"] = round(new_max, 1)

    # ── Validate and apply the daily reminder check time ──────────────────────
    if "reminder_check_time" in body:
        t = (body.get("reminder_check_time") or "").strip()
        if not _valid_hhmm(t):
            return jsonify({"error": "reminder_check_time must be HH:MM (24-hour)"}), 400
        current["reminder_check_time"] = t
        # Reschedule the live job immediately so the new time takes effect
        # without a container restart. Imported lazily to avoid pulling the
        # scheduler (and APScheduler) into every settings read.
        try:
            from .scheduler import reschedule_daily
            reschedule_daily(t)
        except Exception:
            # A scheduler that is not running (e.g. under tests) must not block
            # a settings save — the new time is persisted regardless.
            pass

    save_settings(current)
    return jsonify(current)


def _valid_hhmm(value: str) -> bool:
    """True if ``value`` is a valid 24-hour ``HH:MM`` time string."""
    parts = value.split(":")
    if len(parts) != 2:
        return False
    try:
        hh, mm = int(parts[0]), int(parts[1])
    except ValueError:
        return False
    return 0 <= hh <= 23 and 0 <= mm <= 59
