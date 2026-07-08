"""
routes/auth.py
--------------
Single-admin authentication, first-run onboarding, and the access guard for the
whole API.

Why this exists
---------------
AutoLedger shipped with **no authentication** — the README simply said "keep it
behind a VPN". That violates the standing rule that every app gets a
user+password authority with a forced first-run onboarding step. This module
adds exactly that, sized for a single-user home-lab tool:

* **One admin account.** No multi-user, no roles. Username + password is enough
  authority for a personal cost tracker.
* **Argon2id hashing** (``argon2-cffi``) — memory-hard, the current best-practice
  password hash. The plaintext password is never stored or logged.
* **Forced onboarding.** Until an account exists, the only things the API will
  do are report status and accept the create-admin call. The SPA renders an
  onboarding screen that blocks all other use.
* **Signed-cookie sessions.** Flask's built-in ``itsdangerous`` session, signed
  with a persistent secret (``data/session.key``) so logins survive restarts.

Storage
-------
The credential lives in ``<DATA_DIR>/auth.json`` (inside the gitignored data
volume — never committed)::

    { "username": "...", "password_hash": "$argon2id$...", "created_at": "ISO" }

**No secret is ever exposed through a GET.** ``/api/auth/status`` returns only
booleans and the username, never the hash.

Guard
-----
:func:`register_auth_guard` installs a ``before_request`` hook that protects
every ``/api/*`` route except the small unauthenticated allow-list (health and
the auth status/login/onboard calls). Static assets and the SPA shell are served
freely — the frontend itself decides what to render based on
``/api/auth/status``.
"""

from __future__ import annotations

import logging
import os
from datetime import datetime

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerifyMismatchError
from flask import Blueprint, jsonify, request, session

from .data import _load_json, _save_json
from .logging_config import log_event

auth_bp = Blueprint("auth", __name__)

# Argon2id hasher with library defaults (sensible memory/time cost for a login).
_hasher = PasswordHasher()

# Minimum password length. Deliberately modest — this is a personal tool, not a
# bank — but enough to stop trivially guessable one-character passwords.
_MIN_PASSWORD_LEN = 8


# ── Storage paths (resolved at call time for test isolation) ──────────────────

def _data_dir() -> str:
    """Resolve the data directory at call time so tests can redirect it."""
    return os.environ.get("DATA_DIR", "/data")


def _auth_file() -> str:
    """Path to the credential file inside the data volume."""
    return os.path.join(_data_dir(), "auth.json")


def _session_key_file() -> str:
    """Path to the persistent Flask session-signing secret."""
    return os.path.join(_data_dir(), "session.key")


# ── Credential persistence ────────────────────────────────────────────────────

def load_auth() -> dict | None:
    """
    Return the stored credential dict, or ``None`` if no account exists yet.

    ``_load_json`` returns ``[]`` for a missing file; we normalise that and any
    non-dict content to ``None`` so "not onboarded" is a single clear signal.
    """
    try:
        stored = _load_json(_auth_file())
    except Exception as e:  # corrupt auth.json — fail loud, treat as no account
        log_event("auth_load_failed", level=logging.ERROR, error=str(e))
        return None
    return stored if isinstance(stored, dict) and stored.get("username") else None


def save_auth(record: dict) -> None:
    """Persist the credential dict via the shared atomic writer."""
    _save_json(_auth_file(), record)


def is_onboarded() -> bool:
    """True once an admin account has been created."""
    return load_auth() is not None


# ── Session secret ────────────────────────────────────────────────────────────

def get_session_secret() -> str:
    """
    Return the persistent Flask session-signing secret, creating it on first use.

    This is infrastructure (it signs the session cookie), not a user secret, so
    it lives in its own ``0600`` file in the data volume and persists across
    restarts — otherwise every container restart would invalidate all logins.
    """
    path = _session_key_file()
    if os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            return f.read().strip()

    secret = os.urandom(32).hex()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(secret)
    log_event("session_secret_created", file="session.key")
    return secret


# ── Endpoints ─────────────────────────────────────────────────────────────────

@auth_bp.route("/auth/status", methods=["GET"])
def auth_status():
    """
    Report onboarding + authentication state. **Unauthenticated** — the SPA
    calls this on load to decide whether to show onboarding, login, or the app.

    Returns only booleans and the (non-secret) username; never the hash.
    """
    record = load_auth()
    return jsonify({
        "onboarded":     record is not None,
        "authenticated": bool(session.get("user")),
        "username":      session.get("user"),
    })


@auth_bp.route("/auth/onboard", methods=["POST"])
def onboard():
    """
    Create the single admin account. Only valid on first run — once an account
    exists this returns 409 so the endpoint can never be used to silently
    overwrite the credential.

    On success the new admin is logged straight in (session established).
    """
    if is_onboarded():
        return jsonify({"error": "An account already exists"}), 409

    body = request.get_json(force=True, silent=True) or {}
    username = (body.get("username") or "").strip()
    password = body.get("password") or ""

    if not username:
        return jsonify({"error": "username is required"}), 400
    if len(password) < _MIN_PASSWORD_LEN:
        return jsonify(
            {"error": f"password must be at least {_MIN_PASSWORD_LEN} characters"}
        ), 400

    record = {
        "username":      username,
        "password_hash": _hasher.hash(password),
        "created_at":    datetime.now().isoformat(),
    }
    save_auth(record)
    session["user"] = username
    session.permanent = True
    log_event("onboarded", username=username)
    return jsonify({"ok": True, "username": username}), 201


@auth_bp.route("/auth/login", methods=["POST"])
def login():
    """
    Authenticate against the stored credential and establish a session.

    Returns a generic 401 on any failure (unknown user OR wrong password) so the
    response does not reveal whether the username was correct.
    """
    record = load_auth()
    if record is None:
        # Not onboarded yet — steer the client to onboarding rather than login.
        return jsonify({"error": "No account exists yet", "onboarding_required": True}), 409

    body = request.get_json(force=True, silent=True) or {}
    username = (body.get("username") or "").strip()
    password = body.get("password") or ""

    ok = username == record["username"]
    if ok:
        try:
            _hasher.verify(record["password_hash"], password)
        except (VerifyMismatchError, InvalidHashError):
            ok = False

    if not ok:
        log_event("login_failed", level=logging.WARNING, username=username)
        return jsonify({"error": "Invalid username or password"}), 401

    # Opportunistically upgrade the stored hash if Argon2 parameters have moved
    # on since it was created — transparent to the user, keeps hashes current.
    if _hasher.check_needs_rehash(record["password_hash"]):
        record["password_hash"] = _hasher.hash(password)
        save_auth(record)
        log_event("password_rehashed", username=username)

    session["user"] = username
    session.permanent = True
    log_event("login_ok", username=username)
    return jsonify({"ok": True, "username": username})


@auth_bp.route("/auth/logout", methods=["POST"])
def logout():
    """Clear the session. Idempotent — always returns ok."""
    user = session.pop("user", None)
    if user:
        log_event("logout", username=user)
    return jsonify({"ok": True})


# ── Access guard ──────────────────────────────────────────────────────────────

# API paths that never require authentication. Everything else under /api/ does.
_PUBLIC_API_PATHS = frozenset({
    "/api/health",
    "/api/public/stats",
    "/api/auth/status",
    "/api/auth/login",
    "/api/auth/onboard",
})


def register_auth_guard(app) -> None:
    """
    Install the ``before_request`` guard that protects the API.

    Rules:
      * Non-``/api`` requests (the SPA shell, static assets, favicon) pass
        through — the frontend decides what to render.
      * Public API paths (health + auth status/login/onboard) pass through.
      * Before onboarding, every other API call returns 403 with an
        ``onboarding_required`` flag so the SPA can force the onboarding screen.
      * After onboarding, every other API call requires a valid session, else
        401.
    """
    @app.before_request
    def _require_auth():
        path = request.path
        if not path.startswith("/api/"):
            return None
        if path in _PUBLIC_API_PATHS:
            return None
        if not is_onboarded():
            return jsonify(
                {"error": "Onboarding required", "onboarding_required": True}
            ), 403
        if not session.get("user"):
            return jsonify({"error": "Authentication required"}), 401
        return None
