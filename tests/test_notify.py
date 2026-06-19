"""
tests/test_notify.py
--------------------
Tests for at-rest secret encryption and the notification-config endpoints,
focused on the security guarantee: secrets are encrypted on disk and never
returned through a GET.
"""

import json
import os

from routes import crypto
from routes import data as data_module

# ── Crypto round-trip ──────────────────────────────────────────────────────────

def test_encrypt_decrypt_round_trip():
    token = crypto.encrypt_secret("hunter2")
    assert token != "hunter2"
    assert crypto.is_encrypted(token)
    assert crypto.decrypt_secret(token) == "hunter2"


def test_encrypt_is_idempotent():
    once = crypto.encrypt_secret("abc")
    twice = crypto.encrypt_secret(once)
    assert once == twice  # already-encrypted value is not double-wrapped


def test_decrypt_passes_through_plaintext():
    # A value seeded from an env var (no prefix) is treated as plaintext.
    assert crypto.decrypt_secret("plain") == "plain"


def test_blank_secret_passes_through():
    assert crypto.encrypt_secret("") == ""
    assert crypto.encrypt_secret(None) is None


# ── Config endpoint never leaks secrets ────────────────────────────────────────

def test_get_config_masks_secrets(client):
    client.post("/api/notify/config", json={
        "email": {"host": "smtp.example.com", "password": "smtp-secret"},
        "homeassistant": {"base_url": "http://ha:8123", "token": "ha-secret"},
    })
    cfg = client.get("/api/notify/config").get_json()
    # Booleans tell the UI a secret is stored; the values themselves never appear.
    assert cfg["email"]["password_set"] is True
    assert "password" not in cfg["email"]
    assert cfg["homeassistant"]["token_set"] is True
    assert "token" not in cfg["homeassistant"]


def test_secrets_are_encrypted_on_disk(client):
    client.post("/api/notify/config", json={
        "email": {"password": "smtp-secret"},
        "homeassistant": {"token": "ha-secret"},
    })
    raw = json.loads(
        open(os.path.join(data_module._DATA_DIR, "notify.json")).read()
    )
    assert raw["email"]["password"].startswith("enc:v1:")
    assert "smtp-secret" not in json.dumps(raw)
    assert raw["homeassistant"]["token"].startswith("enc:v1:")


def test_blank_password_keeps_existing_secret(client):
    client.post("/api/notify/config", json={"email": {"password": "first"}})
    # Saving other fields with a blank password must not wipe the stored secret.
    client.post("/api/notify/config", json={"email": {"host": "smtp.new.com"}})
    raw = json.loads(
        open(os.path.join(data_module._DATA_DIR, "notify.json")).read()
    )
    assert crypto.decrypt_secret(raw["email"]["password"]) == "first"
    assert raw["email"]["host"] == "smtp.new.com"
