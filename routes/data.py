"""
routes/data.py
--------------
Shared data-access helpers used by all route modules.

Keeping load/save in one place means the storage backend (currently
flat JSON files) can be swapped out — e.g. to SQLite — without
touching any route code.

Files managed:
  costs.json    — all cost records (each has a vehicle_id field)
  vehicles.json — all vehicle records
  settings.json — user preferences (currency, categories)

Changelog:
  v1.0.0  Initial — JSON file storage
  v1.2.0  Extracted into shared module; added make_id helper
  v1.4.0  Added load_vehicles / save_vehicles for multi-vehicle support
  v1.7.0  Atomic writes (tmp + os.replace) to prevent corruption on crash;
           _parse_date_to_iso moved here so importexport and reports share it;
           single load_data call in last-odometer helpers
"""

import json
import logging
import os
import tempfile
import uuid
from datetime import datetime

from .logging_config import log_event

# ── Configuration ─────────────────────────────────────────────────────────────

_DATA_DIR     = os.environ.get("DATA_DIR", "/data")
DATA_FILE     = os.path.join(_DATA_DIR, "costs.json")
VEHICLES_FILE = os.path.join(_DATA_DIR, "vehicles.json")
SETTINGS_FILE = os.path.join(_DATA_DIR, "settings.json")


# ── ID generation ─────────────────────────────────────────────────────────────

def make_id() -> str:
    """Return a new UUID4 string to use as a record ID."""
    return str(uuid.uuid4())


# ── Date normalisation (shared by importexport and reports) ───────────────────

_DATE_FORMATS = ("%Y-%m-%d", "%d/%m/%Y", "%m/%d/%Y", "%Y/%m/%d", "%d-%m-%Y")

def parse_date_to_iso(date_str: str) -> str:
    """
    Normalise any date string to ISO-8601 (YYYY-MM-DD).
    Tries DD/MM/YYYY before MM/DD/YYYY since LubeLogger is a UK app.
    Returns the input unchanged if no format matches (safe fallback).
    """
    if not date_str:
        return date_str
    for fmt in _DATE_FORMATS:
        try:
            return datetime.strptime(date_str.strip(), fmt).strftime("%Y-%m-%d")
        except ValueError:
            continue
    return date_str.strip()


# ── Atomic JSON I/O ───────────────────────────────────────────────────────────

def _load_json(path: str) -> list:
    """
    Load a JSON list from disk.
    Returns [] if the file does not exist.
    Raises JSONDecodeError if the file is corrupt — callers should surface
    this rather than silently swallowing it.
    """
    if not os.path.exists(path):
        return []
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def _save_json(path: str, data) -> None:
    """
    Atomically persist data to disk.

    Writes to a temporary file in the same directory, then uses os.replace()
    (an atomic operation on POSIX systems) to swap it into place. This means
    a crash or power loss during the write can never produce a corrupt or
    truncated file — the old file remains intact until the new one is complete.

    Works correctly when two Gunicorn workers race to write (last writer wins,
    no partial interleaving). For true concurrent safety a file lock would be
    needed, but with restart: unless-stopped and a single user this is adequate.
    """
    os.makedirs(os.path.dirname(path), exist_ok=True)
    dir_name = os.path.dirname(path)
    # Write to a temp file in the same directory so os.replace is atomic
    fd, tmp_path = tempfile.mkstemp(dir=dir_name, suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
        os.replace(tmp_path, path)  # atomic on POSIX
    except Exception as e:
        # Fail loud (ADR / project principle): record the failure with enough
        # context to debug before re-raising. The caller still sees the
        # exception — we only make sure it leaves a trace in the logs, which the
        # app previously did not do at all.
        log_event(
            "save_failed",
            level=logging.ERROR,
            file=os.path.basename(path),
            error=str(e),
        )
        # Clean up the temp file if anything went wrong
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise


# ── Cost records ──────────────────────────────────────────────────────────────

def load_data() -> list:
    """Read and return all cost records from disk."""
    return _load_json(DATA_FILE)


def save_data(data: list) -> None:
    """Atomically persist all cost records to disk."""
    _save_json(DATA_FILE, data)


# ── Vehicles ──────────────────────────────────────────────────────────────────

def load_vehicles() -> list:
    """Read and return all vehicle records from disk."""
    return _load_json(VEHICLES_FILE)


def save_vehicles(vehicles: list) -> None:
    """Atomically persist all vehicle records to disk."""
    _save_json(VEHICLES_FILE, vehicles)
