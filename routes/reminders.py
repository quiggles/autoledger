"""
routes/reminders.py
-------------------
Service / MOT / Tax / Insurance (and custom) reminders — date- and/or
mileage-based — surfaced in the UI and pushed to Home Assistant and/or email.

Model (``<DATA_DIR>/reminders.json``)
-------------------------------------
Each reminder belongs to a vehicle and may trigger on a **date**, a **mileage**,
or both (whichever comes first)::

    {
      "id":            "uuid4",
      "vehicle_id":    "uuid4",
      "type":          "MOT" | "Service" | "Tax" | "Insurance" | "Custom",
      "label":         "MOT",            # display label (custom types name it)
      "due_date":      "YYYY-MM-DD" | null,
      "due_mileage":   60000 | null,
      "recur_months":  12 | null,        # advance by this on completion
      "recur_miles":   10000 | null,     # advance by this on completion
      "lead_days":     30,               # warn N days before the date
      "lead_miles":    500,              # warn N miles before the mileage
      "notify":        true,             # push to channels (vs in-app only)
      "last_notified": "YYYY-MM-DD" | null,
      "created_at":    "ISO-8601"
    }

Status evaluation
-----------------
"Current mileage" is the highest fuel odometer recorded for the vehicle. A
reminder's overall status is the worse of its date and mileage status:

    overdue  — past the due date OR past the due mileage
    due      — within lead_days of the date OR within lead_miles of the mileage
    ok       — otherwise

All user-facing strings are human-readable ("due in 12 days", "in 350 miles"),
never raw cron or ISO durations, per the project standing rules.

Notification
------------
:func:`evaluate_and_notify` is called by the scheduler (daily) and by the manual
"check now" endpoint. It pushes a per-reminder Home Assistant sensor state and,
for reminders that are newly due/overdue today, sends **one digest email** and
optional HA notify-service messages. A ``last_notified`` date stamp caps external
notifications at one per reminder per day so an overdue item cannot spam.
"""

from __future__ import annotations

import logging
import os
import re
from datetime import date, datetime

from dateutil.relativedelta import relativedelta
from flask import Blueprint, jsonify, request

from . import notify
from .data import _load_json, _save_json, load_data, load_vehicles, make_id
from .logging_config import log_event

reminders_bp = Blueprint("reminders", __name__)

# Reminder types the UI offers. "Custom" lets the user name their own.
REMINDER_TYPES = ("MOT", "Service", "Tax", "Insurance", "Custom")


# ── Storage ───────────────────────────────────────────────────────────────────

def _reminders_file() -> str:
    """Path to the reminders file inside the data volume."""
    return os.path.join(os.environ.get("DATA_DIR", "/data"), "reminders.json")


def load_reminders() -> list:
    """Load all reminder records (empty list if none / unreadable)."""
    try:
        data = _load_json(_reminders_file())
        return data if isinstance(data, list) else []
    except Exception as e:
        log_event("reminders_load_failed", level=logging.ERROR, error=str(e))
        return []


def save_reminders(reminders: list) -> None:
    """Persist all reminder records atomically."""
    _save_json(_reminders_file(), reminders)


# ── Mileage helper ────────────────────────────────────────────────────────────

def _current_mileage(vehicle_id: str, costs: list | None = None) -> float | None:
    """
    Highest fuel odometer recorded for a vehicle — our best estimate of current
    mileage. Returns ``None`` if no odometer readings exist.
    """
    costs = costs if costs is not None else load_data()
    readings = []
    for c in costs:
        if c.get("vehicle_id") != vehicle_id or c.get("category") != "Fuel":
            continue
        raw = c.get("odometer")
        if raw is None or raw == "":
            continue
        try:
            readings.append(float(raw))
        except (TypeError, ValueError):
            continue
    return max(readings) if readings else None


# ── Status evaluation ─────────────────────────────────────────────────────────

def _human_days(days: int) -> str:
    """Render a day delta as friendly text: 'in 12 days' / '3 days ago' / 'today'."""
    if days == 0:
        return "today"
    if days > 0:
        return f"in {days} day{'s' if days != 1 else ''}"
    n = abs(days)
    return f"{n} day{'s' if n != 1 else ''} ago"


def _human_miles(miles: float) -> str:
    """Render a mileage delta as friendly text: 'in 350 miles' / '120 miles over'."""
    n = round(miles)
    if n >= 0:
        return f"in {n:,} mile{'s' if n != 1 else ''}"
    return f"{abs(n):,} mile{'s' if abs(n) != 1 else ''} over"


def evaluate_reminder(rem: dict, current_mileage: float | None,
                      today: date | None = None) -> dict:
    """
    Compute live status for a single reminder against today's date and the
    vehicle's current mileage.

    Returns the reminder enriched with:
      status         — "ok" | "due" | "overdue"
      days_until     — int or None (date-based)
      miles_until    — float or None (mileage-based)
      current_mileage
      message        — human-readable summary
    """
    today = today or date.today()
    statuses = []   # collected sub-statuses; overall = worst of them
    days_until = None
    miles_until = None
    parts = []

    # ── Date dimension ────────────────────────────────────────────────────────
    if rem.get("due_date"):
        try:
            due = datetime.strptime(rem["due_date"], "%Y-%m-%d").date()
            days_until = (due - today).days
            lead = int(rem.get("lead_days", 30))
            if days_until < 0:
                statuses.append("overdue")
            elif days_until <= lead:
                statuses.append("due")
            else:
                statuses.append("ok")
            parts.append(f"{_human_days(days_until)} ({rem['due_date']})")
        except ValueError:
            pass

    # ── Mileage dimension ─────────────────────────────────────────────────────
    if rem.get("due_mileage") is not None and current_mileage is not None:
        try:
            due_m = float(rem["due_mileage"])
            miles_until = due_m - current_mileage
            lead_m = float(rem.get("lead_miles", 500))
            if miles_until < 0:
                statuses.append("overdue")
            elif miles_until <= lead_m:
                statuses.append("due")
            else:
                statuses.append("ok")
            parts.append(_human_miles(miles_until))
        except (TypeError, ValueError):
            pass

    # Overall status is the most urgent sub-status.
    if "overdue" in statuses:
        status = "overdue"
    elif "due" in statuses:
        status = "due"
    elif statuses:
        status = "ok"
    else:
        status = "ok"  # nothing to evaluate (no date, no usable mileage)

    label = rem.get("label") or rem.get("type") or "Reminder"
    message = f"{label} {' / '.join(parts)}" if parts else f"{label} — no due date or mileage set"

    return {
        **rem,
        "status":          status,
        "days_until":      days_until,
        "miles_until":     round(miles_until) if miles_until is not None else None,
        "current_mileage": round(current_mileage) if current_mileage is not None else None,
        "message":         message,
    }


def list_with_status(vehicle_id: str | None = None) -> list:
    """Return all reminders (optionally one vehicle) enriched with live status."""
    reminders = load_reminders()
    if vehicle_id:
        reminders = [r for r in reminders if r.get("vehicle_id") == vehicle_id]

    costs = load_data()
    mileage_cache: dict[str, float | None] = {}
    out = []
    for r in reminders:
        vid = r.get("vehicle_id", "")
        if vid not in mileage_cache:
            mileage_cache[vid] = _current_mileage(vid, costs)
        out.append(evaluate_reminder(r, mileage_cache[vid]))
    return out


# ── Notification dispatch ─────────────────────────────────────────────────────

def _slug(text: str) -> str:
    """Lowercase, underscore-separated slug safe for a Home Assistant entity id."""
    return re.sub(r"[^a-z0-9]+", "_", (text or "").lower()).strip("_") or "x"


def evaluate_and_notify(force: bool = False) -> dict:
    """
    Evaluate every reminder, push Home Assistant sensor states, and send a digest
    email for reminders that are newly due/overdue today.

    Parameters
    ----------
    force : if True, ignore the once-per-day ``last_notified`` guard (used by the
            manual "check now" button so the user always gets feedback).

    Returns a summary dict with counts for the caller / logs.
    """
    cfg = notify.load_notify_config()
    vehicles = {v["id"]: v for v in load_vehicles()}
    costs = load_data()
    reminders = load_reminders()
    today_iso = date.today().isoformat()

    ha_enabled = cfg["homeassistant"].get("enabled")
    email_enabled = cfg["email"].get("enabled")

    mileage_cache: dict[str, float | None] = {}
    newly_due = []          # reminders that crossed into due/overdue today
    evaluated = 0
    changed = False

    for rem in reminders:
        vid = rem.get("vehicle_id", "")
        if vid not in mileage_cache:
            mileage_cache[vid] = _current_mileage(vid, costs)
        ev = evaluate_reminder(rem, mileage_cache[vid])
        evaluated += 1

        vehicle_name = vehicles.get(vid, {}).get("name", "vehicle")

        # Push a per-reminder HA sensor state so the user can build dashboards
        # and automations. State = status; attributes carry the detail.
        if ha_enabled:
            entity = f"sensor.autoledger_{_slug(vehicle_name)}_{_slug(ev.get('label') or ev.get('type'))}"
            notify.push_ha_state(
                entity,
                ev["status"],
                {
                    "friendly_name": f"{vehicle_name} {ev.get('label') or ev.get('type')}",
                    "due_date":      rem.get("due_date"),
                    "due_in_days":   ev["days_until"],
                    "due_mileage":   rem.get("due_mileage"),
                    "miles_until":   ev["miles_until"],
                    "message":       ev["message"],
                },
                cfg,
            )

        # Collect newly-due items for external notification (once/day unless forced).
        if ev["status"] in ("due", "overdue") and rem.get("notify", True):
            if force or rem.get("last_notified") != today_iso:
                newly_due.append((rem, ev, vehicle_name))

    # Send one digest email + HA notify messages for the batch.
    emailed = False
    if newly_due and (email_enabled or ha_enabled):
        lines = [f"• {vn}: {ev['message']} [{ev['status'].upper()}]" for _, ev, vn in newly_due]
        body = "The following AutoLedger reminders are due:\n\n" + "\n".join(lines)

        if email_enabled:
            ok, _ = notify.send_email(
                f"AutoLedger: {len(newly_due)} reminder(s) due", body, cfg
            )
            emailed = ok
        if ha_enabled:
            notify.call_ha_notify(
                f"{len(newly_due)} vehicle reminder(s) due", "AutoLedger", cfg
            )

        # Stamp so we do not re-notify the same items again today.
        for rem, _, _ in newly_due:
            rem["last_notified"] = today_iso
            changed = True

    if changed:
        save_reminders(reminders)

    summary = {
        "evaluated":  evaluated,
        "newly_due":  len(newly_due),
        "emailed":    emailed,
        "ha_pushed":  bool(ha_enabled),
    }
    log_event("reminders_evaluated", **summary)
    return summary


# ── Validation ────────────────────────────────────────────────────────────────

def _coerce_int(value, field):
    """Coerce an optional numeric field to int, or None for blank. Raises ValueError."""
    if value in (None, ""):
        return None
    return int(float(value))


def _build_reminder(body: dict, existing: dict | None = None) -> dict:
    """
    Build/merge a reminder record from a request body, applying defaults and
    validating. Raises ValueError with a user-facing message on bad input.
    """
    rem = dict(existing) if existing else {
        "id":            make_id(),
        "last_notified": None,
        "created_at":    datetime.now().isoformat(),
    }

    if "vehicle_id" in body or not existing:
        vid = (body.get("vehicle_id") or rem.get("vehicle_id") or "").strip()
        if not vid:
            raise ValueError("vehicle_id is required")
        rem["vehicle_id"] = vid

    if "type" in body or not existing:
        rtype = (body.get("type") or rem.get("type") or "").strip()
        if rtype not in REMINDER_TYPES:
            raise ValueError(f"type must be one of {', '.join(REMINDER_TYPES)}")
        rem["type"] = rtype

    if "label" in body:
        rem["label"] = (body["label"] or "").strip()
    rem.setdefault("label", rem.get("type", ""))

    # Date / mileage targets — at least one must be present after merge.
    if "due_date" in body:
        dd = (body["due_date"] or "").strip()
        if dd:
            try:
                datetime.strptime(dd, "%Y-%m-%d")
            except ValueError:
                raise ValueError("due_date must be YYYY-MM-DD") from None
        rem["due_date"] = dd or None

    for fld in ("due_mileage", "recur_months", "recur_miles", "lead_days", "lead_miles"):
        if fld in body:
            try:
                rem[fld] = _coerce_int(body[fld], fld)
            except (TypeError, ValueError):
                raise ValueError(f"{fld} must be a whole number") from None

    # Sensible defaults for lead times.
    rem.setdefault("due_date", None)
    rem.setdefault("due_mileage", None)
    rem.setdefault("recur_months", None)
    rem.setdefault("recur_miles", None)
    rem.setdefault("lead_days", 30)
    rem.setdefault("lead_miles", 500)
    if "notify" in body:
        rem["notify"] = bool(body["notify"])
    rem.setdefault("notify", True)

    if not rem.get("due_date") and rem.get("due_mileage") is None:
        raise ValueError("Set a due date, a due mileage, or both")

    return rem


# ── Endpoints ─────────────────────────────────────────────────────────────────

@reminders_bp.route("/reminders", methods=["GET"])
def get_reminders():
    """List reminders with live status. Optional ?vehicle_id= filter."""
    vehicle_id = request.args.get("vehicle_id") or None
    return jsonify(list_with_status(vehicle_id))


@reminders_bp.route("/reminders/due", methods=["GET"])
def get_due_reminders():
    """Only due/overdue reminders — drives the dashboard banner."""
    vehicle_id = request.args.get("vehicle_id") or None
    due = [r for r in list_with_status(vehicle_id) if r["status"] in ("due", "overdue")]
    return jsonify(due)


@reminders_bp.route("/reminders", methods=["POST"])
def create_reminder():
    """Create a reminder."""
    body = request.get_json(force=True, silent=True) or {}
    try:
        rem = _build_reminder(body)
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    reminders = load_reminders()
    reminders.append(rem)
    save_reminders(reminders)
    log_event("reminder_created", id=rem["id"], type=rem["type"])
    return jsonify(rem), 201


@reminders_bp.route("/reminders/<rem_id>", methods=["PUT"])
def update_reminder(rem_id):
    """Partial update of a reminder."""
    body = request.get_json(force=True, silent=True) or {}
    reminders = load_reminders()
    for i, r in enumerate(reminders):
        if r["id"] == rem_id:
            try:
                reminders[i] = _build_reminder(body, existing=r)
            except ValueError as e:
                return jsonify({"error": str(e)}), 400
            save_reminders(reminders)
            return jsonify(reminders[i])
    return jsonify({"error": "Reminder not found"}), 404


@reminders_bp.route("/reminders/<rem_id>", methods=["DELETE"])
def delete_reminder(rem_id):
    """Delete a reminder. Idempotent."""
    reminders = load_reminders()
    save_reminders([r for r in reminders if r["id"] != rem_id])
    return jsonify({"ok": True})


@reminders_bp.route("/reminders/<rem_id>/complete", methods=["POST"])
def complete_reminder(rem_id):
    """
    Mark a recurring reminder as done: advance its due date by ``recur_months``
    and/or its due mileage by ``recur_miles`` so the next cycle is scheduled.
    Clears ``last_notified`` so the next cycle can notify afresh. A non-recurring
    reminder is simply cleared (date/mileage nulled) and goes dormant.
    """
    reminders = load_reminders()
    for r in reminders:
        if r["id"] == rem_id:
            if r.get("due_date") and r.get("recur_months"):
                base = datetime.strptime(r["due_date"], "%Y-%m-%d").date()
                # Advance from the later of the due date or today so a long-overdue
                # item lands in the future, not the past.
                anchor = max(base, date.today())
                r["due_date"] = (anchor + relativedelta(months=int(r["recur_months"]))).isoformat()
            elif r.get("due_date"):
                r["due_date"] = None

            if r.get("due_mileage") is not None and r.get("recur_miles"):
                r["due_mileage"] = int(r["due_mileage"]) + int(r["recur_miles"])
            elif r.get("due_mileage") is not None:
                r["due_mileage"] = None

            r["last_notified"] = None
            save_reminders(reminders)
            log_event("reminder_completed", id=rem_id)
            return jsonify(r)
    return jsonify({"error": "Reminder not found"}), 404


@reminders_bp.route("/reminders/evaluate", methods=["POST"])
def evaluate_now():
    """Manually trigger evaluation + notification (the 'check now' button)."""
    summary = evaluate_and_notify(force=True)
    return jsonify(summary)
