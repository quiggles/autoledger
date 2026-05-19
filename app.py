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
"""

from flask import Flask, send_from_directory, request
from routes.costs import costs_bp
from routes.importexport import io_bp
from routes.settings import settings_bp
from routes.vehicles import vehicles_bp
from routes.reports import reports_bp

# ── App factory ───────────────────────────────────────────────────────────────

app = Flask(__name__, static_folder="static")
app.config['SEND_FILE_MAX_AGE_DEFAULT'] = 0  # disable static file caching

app.register_blueprint(costs_bp,    url_prefix="/api")
app.register_blueprint(io_bp,       url_prefix="/api")
app.register_blueprint(settings_bp, url_prefix="/api")
app.register_blueprint(vehicles_bp, url_prefix="/api")
app.register_blueprint(reports_bp,  url_prefix="/api")


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
