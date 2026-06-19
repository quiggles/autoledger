"""
routes/health.py
----------------
Liveness/health endpoint for container orchestration and monitoring.

The user runs Container Radar, Homepage (with siteMonitor) and Portainer and
wants a real health signal rather than a bare TCP check. ``GET /api/health``
returns a small JSON document with the app version and current record counts,
and is wired to the Docker ``HEALTHCHECK`` in the Dockerfile.

This route is intentionally **unauthenticated** (it is on the auth guard's
public allow-list) so a monitor can poll it without a session, and it exposes
**nothing sensitive** — only the version and two integer counts. The counts
double as a cheap "is the storage layer readable?" probe: if the data files are
corrupt the load raises and the endpoint reports ``degraded``.
"""

from __future__ import annotations

import logging

from flask import Blueprint, jsonify

from version import __version__

from .data import load_data, load_vehicles
from .logging_config import log_event

health_bp = Blueprint("health", __name__)


@health_bp.route("/health", methods=["GET"])
def health():
    """
    Report application health.

    Returns 200 with ``status: ok`` when the storage layer is readable, or 503
    with ``status: degraded`` if loading the data files fails — so a monitor
    sees a hard failure rather than a misleading 200.
    """
    try:
        vehicles = load_vehicles()
        records = load_data()
    except Exception as e:
        # Reading failed (e.g. corrupt JSON) — surface it as unhealthy.
        log_event("health_degraded", level=logging.ERROR, error=str(e))
        return jsonify({"status": "degraded", "version": __version__, "error": "storage unreadable"}), 503

    return jsonify({
        "status":   "ok",
        "version":  __version__,
        "vehicles": len(vehicles),
        "records":  len(records),
    })
