"""
routes/public.py
----------------
Unauthenticated, aggregate-only statistics for external dashboards.

Why this exists
---------------
The home-lab Homepage dashboard (gethomepage.dev) shows a live tile per app. It
has no native AutoLedger widget, so it consumes a generic ``customapi`` widget
that expects a **flat JSON object of scalar values** it can map to labels. This
endpoint provides exactly that — the same public-aggregate pattern already used
by the Container Radar app's ``/api/public/stats``.

Security posture
----------------
This route is on the auth guard's public allow-list (see ``routes/auth.py``), so
it needs no session. It therefore exposes **only coarse aggregates** and never
any per-record, per-vehicle, or personally identifying detail:

    * vehicles       — how many vehicles are tracked (int)
    * entries        — how many cost records exist in total (int)
    * ytd_spend      — total spend in the current calendar year, all vehicles
                       combined (float, in the app's base currency)
    * reminders_due  — count of reminders currently due or overdue (int)

``ytd_spend`` is the only mildly sensitive figure (an annual motoring spend
total). It is deliberately a single blended number with no breakdown, and the
app sits behind the LAN reverse proxy, so the exposure is low. If even that is
unwanted, drop the field from the ``mappings:`` in the Homepage widget — the
endpoint stays cheap and the tile simply shows the other three counts.

Robustness
----------
Like the reports layer, every amount is coerced defensively: a single malformed
``amount`` (e.g. ``"n/a"`` from a bad import) is skipped and logged rather than
allowed to 500 the whole endpoint. If the storage layer itself is unreadable the
endpoint returns 503 so a monitor sees a hard failure, mirroring ``/api/health``.
"""

from __future__ import annotations

import logging
from datetime import date

from flask import Blueprint, jsonify

from .data import load_data, load_vehicles, parse_date_to_iso
from .logging_config import log_event
from .reminders import list_with_status

public_bp = Blueprint("public", __name__)


def _amount(record: dict) -> float | None:
    """
    Return a record's ``amount`` as a float, or ``None`` if missing/malformed.

    Mirrors ``routes.reports._amount`` (kept local rather than imported to avoid
    coupling the public surface to the reports module's internals). A bad value
    is logged for visibility and skipped by the caller, so one rogue record can
    never crash the aggregate.
    """
    raw = record.get("amount")
    try:
        return float(raw)
    except (TypeError, ValueError):
        log_event(
            "bad_amount_skipped",
            level=logging.WARNING,
            id=record.get("id"),
            value=raw,
            source="public_stats",
        )
        return None


@public_bp.route("/public/stats", methods=["GET"])
def public_stats():
    """
    Return flat aggregate stats for the Homepage dashboard tile.

    Unauthenticated by design (aggregate-only). Returns 200 with the counts on
    success, or 503 ``degraded`` if the storage layer cannot be read — so the
    dashboard/monitor sees a real failure rather than a misleading zeroed tile.
    """
    try:
        vehicles = load_vehicles()
        costs = load_data()
    except Exception as e:
        # Storage unreadable (e.g. corrupt JSON) — fail loud, same contract as
        # /api/health, rather than pretending everything is zero.
        log_event("public_stats_degraded", level=logging.ERROR, error=str(e))
        return jsonify({"status": "degraded", "error": "storage unreadable"}), 503

    # Year-to-date spend: sum of parseable amounts whose (normalised) date falls
    # in the current calendar year. parse_date_to_iso handles the several date
    # formats the importers accept; a record with no/undated value is ignored.
    this_year = str(date.today().year)
    ytd_spend = 0.0
    for c in costs:
        raw_date = c.get("date")
        if not raw_date:
            continue
        if parse_date_to_iso(raw_date)[:4] != this_year:
            continue
        amt = _amount(c)
        if amt is not None:
            ytd_spend += amt

    # Reminders currently needing attention. list_with_status enriches each
    # reminder with a live "ok" / "due" / "overdue" status; we count the two
    # actionable states. Guarded so a reminders-layer failure degrades this one
    # field to 0 rather than 500ing the whole tile.
    try:
        reminders_due = sum(
            1 for r in list_with_status() if r.get("status") in ("due", "overdue")
        )
    except Exception as e:
        log_event("public_stats_reminders_failed", level=logging.WARNING, error=str(e))
        reminders_due = 0

    return jsonify({
        "vehicles":      len(vehicles),
        "entries":       len(costs),
        "ytd_spend":     round(ytd_spend, 2),
        "reminders_due": reminders_due,
    })
