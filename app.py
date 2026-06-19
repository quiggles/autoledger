"""
AutoLedger — Car Cost Tracker
=====================================
Entry point for the Flask application.

Registers modular route blueprints and serves the static frontend.
All business logic is contained in the /routes/ modules.

Changelog:
  v1.0.0  Initial release — manual entry, summary cards, delete
  v1.1.0  Import/export: AutoLedger JSON and LubeLogger CSV
  v1.2.0  Modular refactor; light/dark mode; Synology-ready compose;
           full code comments; HANDOFF.md; CHANGELOG.md
  v1.3.0  Settings page; custom currency; custom categories; sidebar nav;
           redesigned UI
  v1.4.0  Multi-vehicle support; vehicles blueprint; data.py extended
  v2.0.0  Authentication + first-run onboarding (Argon2id, signed sessions);
           /api/health + Docker HEALTHCHECK; structured logging; configurable
           MPG bounds; service/MOT/tax/insurance reminders with Home Assistant
           + email notifications driven by an in-process daily scheduler.
"""

from flask import Flask, jsonify, request, send_from_directory

from routes.auth import (
    auth_bp,
    get_session_secret,
    register_auth_guard,
)
from routes.costs import costs_bp
from routes.health import health_bp
from routes.importexport import io_bp
from routes.logging_config import configure_logging, log_event
from routes.notify import notify_bp
from routes.reminders import reminders_bp
from routes.reports import reports_bp
from routes.scheduler import start_scheduler
from routes.settings import settings_bp
from routes.vehicles import vehicles_bp
from version import __version__

# ── App factory ───────────────────────────────────────────────────────────────

# Configure structured logging before anything else so startup events are
# captured. Idempotent — safe under repeated imports (tests, reloader).
configure_logging()

app = Flask(__name__, static_folder="static")
app.config['SEND_FILE_MAX_AGE_DEFAULT'] = 0  # disable static file caching

# Sign the session cookie with a persistent secret stored in the data volume so
# logins survive container restarts. Generated on first use.
app.secret_key = get_session_secret()

# Session-cookie hardening. HttpOnly stops client JS reading the cookie;
# SameSite=Lax stops the cookie riding along on cross-site state-changing
# requests (CSRF mitigation). SECURE is deliberately NOT forced: the app is
# commonly served over plain HTTP on a LAN (TLS is terminated upstream by the
# NGINX Proxy Manager), and forcing Secure would break direct HTTP access.
app.config.update(
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
)

# ── Blueprint registry ────────────────────────────────────────────────────────
app.register_blueprint(auth_bp,      url_prefix="/api")
app.register_blueprint(health_bp,    url_prefix="/api")
app.register_blueprint(costs_bp,     url_prefix="/api")
app.register_blueprint(io_bp,        url_prefix="/api")
app.register_blueprint(settings_bp,  url_prefix="/api")
app.register_blueprint(vehicles_bp,  url_prefix="/api")
app.register_blueprint(reports_bp,   url_prefix="/api")
app.register_blueprint(notify_bp,    url_prefix="/api")
app.register_blueprint(reminders_bp, url_prefix="/api")

# Install the authentication guard on all /api/* routes (except the public
# allow-list defined in routes/auth.py). Must run after blueprints register.
register_auth_guard(app)

# Start the in-process daily reminder scheduler. No-op under tests
# (AUTOLEDGER_DISABLE_SCHEDULER=1) and idempotent.
start_scheduler()

log_event("app_started", version=__version__)


# ── Error handling ────────────────────────────────────────────────────────────

@app.errorhandler(500)
def handle_500(e):
    """
    Convert an unhandled exception into a logged JSON error rather than a bare
    HTML stack page. The app previously had no request-error logging at all.
    """
    log_event("request_error", level=40, path=request.path, error=str(e))
    return jsonify({"error": "Internal server error"}), 500


# ── Root route ────────────────────────────────────────────────────────────────

@app.after_request
def add_no_cache(response):
    """Prevent browsers caching JS/CSS so updates deploy immediately."""
    if request.path.startswith('/static/'):
        response.headers['Cache-Control'] = 'no-store, no-cache, must-revalidate'
        response.headers['Pragma'] = 'no-cache'
    return response


@app.route("/")
def index():
    """Serve the single-page frontend."""
    return send_from_directory("static", "index.html")


@app.route("/favicon.ico")
def favicon():
    """Serve favicon to suppress 404 errors in browser console."""
    return send_from_directory("static", "favicon.svg", mimetype="image/svg+xml")


# ── Dev server entry point ─────────────────────────────────────────────────────
# In production (Docker) Gunicorn is used instead (see Dockerfile).

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=False)
