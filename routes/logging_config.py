"""
routes/logging_config.py
------------------------
Centralised structured logging for AutoLedger.

AutoLedger historically had **no logging at all**, which contradicted the
project's "fail loud, never swallow" principle: when a save failed or an import
row blew up, nothing was recorded anywhere a maintainer could see it. This
module fixes that with the smallest possible footprint.

Design
------
- **stdout, key=value lines.** The app runs as a single Gunicorn worker in a
  container; everything written to stdout/stderr is captured by Docker and is
  what Portainer, `docker logs`, and the user's Container Radar / Homepage
  tooling actually surface. A heavyweight JSON-logging stack would add a
  dependency for no real gain at this scale, so we emit compact, greppable
  ``key=value`` records instead.
- **One logger, fetched by name.** Call :func:`get_logger` from any module;
  :func:`configure_logging` is invoked once at app start (in ``app.py``) and is
  idempotent, so repeated imports (e.g. under pytest) never attach duplicate
  handlers.
- **Helper for events.** :func:`log_event` formats a level + event name + a set
  of structured fields, quoting any value that contains spaces, so downstream
  log processors can parse fields reliably.

This module deliberately knows nothing about Flask request context — it is a
plain logging utility so it can be used from the scheduler thread, the crypto
layer, and the route handlers alike.
"""

from __future__ import annotations

import logging
import os
import sys

# Single shared logger name. Everything in the app logs through this one tree so
# a single handler/formatter governs the whole application's output.
_LOGGER_NAME = "autoledger"

# Module-level guard so configure_logging() is genuinely idempotent even if it is
# imported and called from more than one place (app start, tests, etc.).
_configured = False


def configure_logging() -> None:
    """
    Attach a single stdout StreamHandler to the AutoLedger logger.

    Idempotent: safe to call multiple times (e.g. once per pytest module import)
    without stacking duplicate handlers, which would multiply every log line.

    The level is taken from the ``LOG_LEVEL`` environment variable (default
    ``INFO``) so an operator can turn on ``DEBUG`` in a container without a code
    change.
    """
    global _configured
    if _configured:
        return

    level_name = os.environ.get("LOG_LEVEL", "INFO").upper()
    level = getattr(logging, level_name, logging.INFO)

    logger = logging.getLogger(_LOGGER_NAME)
    logger.setLevel(level)
    # Do not propagate to the root logger — Gunicorn installs its own root
    # handlers and we do not want every line duplicated.
    logger.propagate = False

    handler = logging.StreamHandler(stream=sys.stdout)
    handler.setFormatter(
        logging.Formatter("%(asctime)s level=%(levelname)s %(message)s")
    )
    logger.addHandler(handler)

    _configured = True


def get_logger() -> logging.Logger:
    """Return the shared AutoLedger logger, configuring it on first use."""
    if not _configured:
        configure_logging()
    return logging.getLogger(_LOGGER_NAME)


def _format_fields(fields: dict) -> str:
    """
    Render a dict as ``key=value`` pairs, quoting values that contain spaces or
    are empty so the output stays unambiguously parseable.
    """
    parts = []
    for key, value in fields.items():
        text = "" if value is None else str(value)
        if text == "" or " " in text or "=" in text:
            text = f'"{text}"'
        parts.append(f"{key}={text}")
    return " ".join(parts)


def log_event(event: str, level: int = logging.INFO, **fields) -> None:
    """
    Emit one structured log record.

    Parameters
    ----------
    event  : short stable event name, e.g. ``"save_failed"`` or ``"login_ok"``.
    level  : a ``logging`` level constant (default ``logging.INFO``).
    fields : arbitrary structured context rendered as ``key=value`` pairs.

    Example
    -------
    ``log_event("save_failed", level=logging.ERROR, file="costs.json", error=str(e))``
    produces::

        2026-06-18 21:05:00 level=ERROR event=save_failed file=costs.json error="..."
    """
    logger = get_logger()
    message = "event=" + event
    if fields:
        message += " " + _format_fields(fields)
    logger.log(level, message)
