"""
routes/crypto.py
----------------
At-rest encryption for **secrets only** (not the cost data).

Design decision (see ADR 0006)
------------------------------
AutoLedger's cost/vehicle/settings JSON deliberately stays **plaintext** so the
ADR 0001 promise — "open it in any editor, diff it, back it up by copying the
folder" — survives. But operational *secrets* (the SMTP password used to send
reminder emails, the Home Assistant long-lived access token) must not sit in
plaintext on disk, per the project's "secrets encrypted at rest" standing rule.

This module provides exactly that narrow capability: encrypt/decrypt individual
short string values with Fernet (AES-128-CBC + HMAC, from the ``cryptography``
library). The symmetric key is **app-managed**, generated once and stored in
``<DATA_DIR>/secret.key`` with ``0600`` permissions. It is NOT derived from the
login password, so resetting the admin password never destroys stored secrets.

Encrypted values are tagged with an ``enc:v1:`` prefix. That lets callers:
  * tell an already-encrypted value from a plaintext one (idempotent re-saves),
  * seed a secret from an environment variable on first run (plaintext in →
    encrypted at rest), and
  * migrate the scheme later (``enc:v2:`` …) without ambiguity.

The key file lives inside the gitignored ``data/`` volume, so it is never
committed and travels with the data it protects when the volume is backed up.
"""

from __future__ import annotations

import logging
import os

from cryptography.fernet import Fernet, InvalidToken

from .logging_config import log_event

# Marker that prefixes every ciphertext we produce. Anything without this prefix
# is treated as plaintext (e.g. a value just seeded from an env var).
_ENC_PREFIX = "enc:v1:"


def _data_dir() -> str:
    """
    Resolve the data directory at call time (not import time).

    Reading the env on each call keeps the module in step with the test harness,
    which redirects ``DATA_DIR`` to a temp directory before the app is imported.
    """
    return os.environ.get("DATA_DIR", "/data")


def _key_path() -> str:
    """Absolute path to the Fernet key file inside the data volume."""
    return os.path.join(_data_dir(), "secret.key")


def _load_or_create_key() -> bytes:
    """
    Return the raw Fernet key, generating and persisting one on first use.

    The key file is created with ``0600`` (owner read/write only) so other users
    on the host cannot read it. Generation is a one-off: once the file exists it
    is always reused, so previously-encrypted secrets remain decryptable.
    """
    path = _key_path()
    if os.path.exists(path):
        with open(path, "rb") as f:
            return f.read().strip()

    # First run: mint a new key and lock the file down.
    os.makedirs(os.path.dirname(path), exist_ok=True)
    key = Fernet.generate_key()
    # Open with restrictive permissions from the start to avoid a brief window
    # where the key is world-readable between create and chmod.
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "wb") as f:
        f.write(key)
    log_event("crypto_key_created", file="secret.key")
    return key


def _fernet() -> Fernet:
    """Construct a Fernet instance from the app-managed key."""
    return Fernet(_load_or_create_key())


def is_encrypted(value: str | None) -> bool:
    """True if ``value`` is one of our ciphertext strings."""
    return isinstance(value, str) and value.startswith(_ENC_PREFIX)


def encrypt_secret(plaintext: str | None) -> str | None:
    """
    Encrypt a short secret string, returning a prefixed ciphertext token.

    Idempotent: an already-encrypted value is returned unchanged, so re-saving a
    settings object that still holds an encrypted secret does not double-encrypt
    it. Empty/None inputs pass straight through (nothing to protect).
    """
    if not plaintext:
        return plaintext
    if is_encrypted(plaintext):
        return plaintext
    token = _fernet().encrypt(plaintext.encode("utf-8")).decode("ascii")
    return _ENC_PREFIX + token


def decrypt_secret(value: str | None) -> str | None:
    """
    Decrypt a value produced by :func:`encrypt_secret`.

    A value without the ``enc:v1:`` prefix is assumed to be plaintext (e.g. just
    seeded from an env var) and returned as-is. A corrupt or wrong-key token is
    logged and treated as empty rather than crashing the caller — a reminder
    email that cannot authenticate should degrade, not take down the request.
    """
    if not value:
        return value
    if not is_encrypted(value):
        return value
    token = value[len(_ENC_PREFIX):]
    try:
        return _fernet().decrypt(token.encode("ascii")).decode("utf-8")
    except InvalidToken:
        log_event(
            "secret_decrypt_failed",
            level=logging.ERROR,
            reason="invalid_token_or_wrong_key",
        )
        return ""
