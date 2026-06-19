"""
routes/notify.py
----------------
Notification channels for reminders: SMTP email and Home Assistant.

Both channels are optional and independently toggleable, configured entirely in
the UI per the project's "settings in the UI" + "email standing rule" +
"secrets encrypted at rest" standing rules.

Storage & secrets
-----------------
Channel configuration lives in ``<DATA_DIR>/notify.json``. The two secret fields
— the SMTP password and the Home Assistant long-lived access token — are
**encrypted at rest** via :mod:`routes.crypto` (Fernet). They are:

  * **seeded from environment variables on first run** (``SMTP_PASSWORD``,
    ``HA_TOKEN``) so a fresh deployment can be pre-provisioned, then encrypted;
  * **never returned by a GET** — :func:`get_config` masks them to empty strings
    and exposes only ``*_set`` booleans so the UI can show "saved / not saved";
  * **only decrypted in-process** at send time.

Endpoints
---------
  GET  /api/notify/config        — masked config (no secrets)
  POST /api/notify/config        — save config (blank secret = keep existing)
  POST /api/notify/test-email    — send a test email with the saved/posted config
  POST /api/notify/test-ha       — push a test state to Home Assistant

The module also exposes :func:`send_email`, :func:`push_ha_state` and
:func:`call_ha_notify` for the reminders engine to use directly.
"""

from __future__ import annotations

import json
import logging
import os
import smtplib
import urllib.error
import urllib.request
from email.message import EmailMessage

from flask import Blueprint, jsonify, request

from .crypto import decrypt_secret, encrypt_secret
from .data import _load_json, _save_json
from .logging_config import log_event

notify_bp = Blueprint("notify", __name__)


# ── Storage ───────────────────────────────────────────────────────────────────

def _notify_file() -> str:
    """Path to the notification-config file inside the data volume."""
    return os.path.join(os.environ.get("DATA_DIR", "/data"), "notify.json")


def _defaults() -> dict:
    """
    Default notification config. Secrets are **seeded from the environment** on
    first run (encrypted immediately) so a deployment can be pre-provisioned via
    compose env vars without ever writing a plaintext secret to disk.
    """
    email_pw = os.environ.get("SMTP_PASSWORD", "")
    ha_token = os.environ.get("HA_TOKEN", "")
    return {
        "email": {
            "enabled":   False,
            "host":      os.environ.get("SMTP_HOST", "smtp.resend.com"),
            "port":      int(os.environ.get("SMTP_PORT", "587")),
            "username":  os.environ.get("SMTP_USERNAME", "resend"),
            "password":  encrypt_secret(email_pw) if email_pw else "",
            "from_addr": os.environ.get("SMTP_FROM", ""),
            "to_addr":   os.environ.get("SMTP_TO", ""),
        },
        "homeassistant": {
            "enabled":        False,
            "base_url":       os.environ.get("HA_BASE_URL", "http://192.168.0.200:8123"),
            "token":          encrypt_secret(ha_token) if ha_token else "",
            "notify_service": os.environ.get("HA_NOTIFY_SERVICE", ""),
        },
    }


def load_notify_config() -> dict:
    """
    Load notification config, merging stored values over defaults so new keys in
    future versions always have a value. On first run this also persists the
    env-seeded defaults so the secrets are written back encrypted.
    """
    try:
        stored = _load_json(_notify_file())
    except Exception as e:
        log_event("notify_config_load_failed", level=logging.ERROR, error=str(e))
        stored = None

    base = _defaults()
    if not isinstance(stored, dict):
        # First run — persist the env-seeded defaults (secrets already encrypted).
        _save_json(_notify_file(), base)
        return base

    # Deep-merge each channel so partial stored configs keep default fallbacks.
    merged = dict(base)
    for channel in ("email", "homeassistant"):
        merged[channel] = {**base[channel], **stored.get(channel, {})}
    return merged


def _save_notify_config(cfg: dict) -> None:
    """Persist notification config atomically."""
    _save_json(_notify_file(), cfg)


# ── Email ─────────────────────────────────────────────────────────────────────

def send_email(subject: str, body: str, cfg: dict | None = None) -> tuple[bool, str]:
    """
    Send a plaintext email via SMTP/STARTTLS on the configured port (default
    587, the submission port used by Resend and Gmail).

    Returns ``(ok, message)`` rather than raising, so a failing reminder email
    degrades gracefully and the caller can surface the reason.
    """
    cfg = cfg or load_notify_config()
    email = cfg["email"]

    host = (email.get("host") or "").strip()
    to_addr = (email.get("to_addr") or "").strip()
    from_addr = (email.get("from_addr") or "").strip() or email.get("username", "")
    if not host or not to_addr:
        return False, "SMTP host and recipient address are required"

    password = decrypt_secret(email.get("password")) or ""

    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = from_addr
    msg["To"] = to_addr
    msg.set_content(body)

    try:
        with smtplib.SMTP(host, int(email.get("port", 587)), timeout=15) as server:
            server.starttls()
            if email.get("username") and password:
                server.login(email["username"], password)
            server.send_message(msg)
        log_event("email_sent", to=to_addr, subject=subject)
        return True, "Email sent"
    except Exception as e:
        log_event("email_failed", level=logging.ERROR, to=to_addr, error=str(e))
        return False, f"Email failed: {e}"


# ── Home Assistant ────────────────────────────────────────────────────────────

def _ha_request(path: str, payload: dict, cfg: dict) -> tuple[bool, str]:
    """
    POST a JSON payload to a Home Assistant REST API path using the bearer token.
    Returns ``(ok, message)`` — never raises into the caller.
    """
    ha = cfg["homeassistant"]
    base = (ha.get("base_url") or "").strip().rstrip("/")
    token = decrypt_secret(ha.get("token")) or ""
    if not base or not token:
        return False, "Home Assistant base URL and token are required"

    url = f"{base}{path}"
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, data=data, method="POST")
    req.add_header("Authorization", f"Bearer {token}")
    req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            return 200 <= resp.status < 300, f"HTTP {resp.status}"
    except urllib.error.HTTPError as e:
        log_event("ha_request_failed", level=logging.ERROR, path=path, status=e.code)
        return False, f"Home Assistant returned HTTP {e.code}"
    except Exception as e:
        log_event("ha_request_failed", level=logging.ERROR, path=path, error=str(e))
        return False, f"Home Assistant error: {e}"


def push_ha_state(entity_id: str, state: str, attributes: dict,
                  cfg: dict | None = None) -> tuple[bool, str]:
    """
    Set the state of a Home Assistant entity via ``POST /api/states/<entity>``.

    This creates/updates an entity the user can put on dashboards or drive
    automations from — the most flexible integration for their HA-heavy setup.
    """
    cfg = cfg or load_notify_config()
    ok, msg = _ha_request(
        f"/api/states/{entity_id}",
        {"state": state, "attributes": attributes},
        cfg,
    )
    if ok:
        log_event("ha_state_pushed", entity=entity_id, state=state)
    return ok, msg


def call_ha_notify(message: str, title: str, cfg: dict | None = None) -> tuple[bool, str]:
    """
    Call a Home Assistant notify service (e.g. ``notify.mobile_app_phone``) if
    one is configured. No-op success if no service is set — pushing states is
    the primary channel and a notify service is an optional extra.
    """
    cfg = cfg or load_notify_config()
    service = (cfg["homeassistant"].get("notify_service") or "").strip()
    if not service:
        return True, "No notify service configured (skipped)"
    # service is "notify.xxx" → POST /api/services/notify/xxx
    domain, _, name = service.partition(".")
    if not name:
        return False, "notify_service must look like notify.mobile_app_xxx"
    return _ha_request(f"/api/services/{domain}/{name}", {"message": message, "title": title}, cfg)


# ── Endpoints ─────────────────────────────────────────────────────────────────

def _masked(cfg: dict) -> dict:
    """
    Return a copy of the config safe to send to the browser: secrets stripped,
    replaced by ``*_set`` booleans. **No secret value ever leaves the server.**
    """
    email = dict(cfg["email"])
    ha = dict(cfg["homeassistant"])
    email_set = bool(email.pop("password", ""))
    ha_set = bool(ha.pop("token", ""))
    return {
        "email":         {**email, "password_set": email_set},
        "homeassistant": {**ha, "token_set": ha_set},
    }


@notify_bp.route("/notify/config", methods=["GET"])
def get_config():
    """Return the masked notification config (no secrets)."""
    return jsonify(_masked(load_notify_config()))


@notify_bp.route("/notify/config", methods=["POST"])
def save_config():
    """
    Save notification config. A **blank** secret field means "keep the existing
    stored secret" (the UI never receives the current secret, so it cannot echo
    it back); a non-blank value is encrypted and stored.
    """
    body = request.get_json(force=True, silent=True) or {}
    cfg = load_notify_config()

    # ── Email channel ─────────────────────────────────────────────────────────
    if "email" in body:
        e = body["email"]
        em = cfg["email"]
        if "enabled" in e:   em["enabled"]   = bool(e["enabled"])
        if "host" in e:      em["host"]       = (e["host"] or "").strip()
        if "port" in e:
            try:
                em["port"] = int(e["port"])
            except (TypeError, ValueError):
                return jsonify({"error": "port must be a number"}), 400
        if "username" in e:  em["username"]  = (e["username"] or "").strip()
        if "from_addr" in e: em["from_addr"] = (e["from_addr"] or "").strip()
        if "to_addr" in e:   em["to_addr"]   = (e["to_addr"] or "").strip()
        # Only overwrite the password when a non-blank value is supplied.
        if e.get("password"):
            em["password"] = encrypt_secret(e["password"])

    # ── Home Assistant channel ────────────────────────────────────────────────
    if "homeassistant" in body:
        h = body["homeassistant"]
        hm = cfg["homeassistant"]
        if "enabled" in h:        hm["enabled"]        = bool(h["enabled"])
        if "base_url" in h:       hm["base_url"]       = (h["base_url"] or "").strip()
        if "notify_service" in h: hm["notify_service"] = (h["notify_service"] or "").strip()
        if h.get("token"):
            hm["token"] = encrypt_secret(h["token"])

    _save_notify_config(cfg)
    log_event("notify_config_saved")
    return jsonify(_masked(cfg))


@notify_bp.route("/notify/test-email", methods=["POST"])
def test_email():
    """
    Send a test email. Uses any posted overrides merged over the saved config so
    the user can verify settings before saving them. A blank password falls back
    to the stored (encrypted) one.
    """
    body = request.get_json(force=True, silent=True) or {}
    cfg = load_notify_config()
    if "email" in body:
        e = body["email"]
        for k in ("host", "port", "username", "from_addr", "to_addr"):
            if k in e:
                cfg["email"][k] = e[k]
        if e.get("password"):
            cfg["email"]["password"] = encrypt_secret(e["password"])

    ok, msg = send_email(
        "AutoLedger test email",
        "This is a test email from AutoLedger. If you received it, your SMTP "
        "settings are working and reminders can be delivered by email.",
        cfg,
    )
    return jsonify({"ok": ok, "message": msg}), (200 if ok else 502)


@notify_bp.route("/notify/test-ha", methods=["POST"])
def test_ha():
    """
    Push a test state to Home Assistant (``sensor.autoledger_test``) to verify
    the base URL and token. Uses posted overrides merged over saved config.
    """
    body = request.get_json(force=True, silent=True) or {}
    cfg = load_notify_config()
    if "homeassistant" in body:
        h = body["homeassistant"]
        for k in ("base_url", "notify_service"):
            if k in h:
                cfg["homeassistant"][k] = h[k]
        if h.get("token"):
            cfg["homeassistant"]["token"] = encrypt_secret(h["token"])

    ok, msg = push_ha_state(
        "sensor.autoledger_test",
        "ok",
        {"friendly_name": "AutoLedger Test", "source": "AutoLedger connectivity test"},
        cfg,
    )
    return jsonify({"ok": ok, "message": msg}), (200 if ok else 502)
