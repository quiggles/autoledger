"""
routes/scheduler.py
-------------------
In-process daily job that evaluates reminders and pushes notifications, so
date-based reminders fire even when nobody has the app open (see ADR 0007).

Why in-process
--------------
AutoLedger runs as a **single Gunicorn worker** (ADR 0002). That makes an
in-process ``APScheduler`` the simplest correct option: exactly one scheduler
instance exists, so there is no multi-worker double-fire to guard against, and
no external cron/host dependency to document and maintain. The job simply calls
:func:`routes.reminders.evaluate_and_notify` once a day at a user-configured
time.

Lifecycle
---------
* :func:`start_scheduler` is called once from ``app.py`` at import time. It is a
  no-op if already started, or if ``AUTOLEDGER_DISABLE_SCHEDULER=1`` (set by the
  test harness so the suite never spins up a background thread).
* :func:`reschedule_daily` is called by the settings route when the user changes
  the reminder check time, so the new time takes effect immediately without a
  container restart.
"""

from __future__ import annotations

import logging
import os

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

from .logging_config import log_event

# Module-level singleton scheduler + a stable job id we can reschedule by name.
_scheduler: BackgroundScheduler | None = None
_JOB_ID = "daily_reminders"

# Default daily check time if settings somehow lack one.
_DEFAULT_TIME = "08:00"


def _parse_time(time_str: str) -> tuple[int, int]:
    """
    Parse an ``HH:MM`` string into ``(hour, minute)``, clamping to valid ranges
    and falling back to 08:00 on anything malformed.
    """
    try:
        hh_s, mm_s = (time_str or _DEFAULT_TIME).split(":")
        hh, mm = int(hh_s), int(mm_s)
        if 0 <= hh <= 23 and 0 <= mm <= 59:
            return hh, mm
    except (ValueError, AttributeError):
        pass
    return 8, 0


def _run_daily_job() -> None:
    """Scheduler entry point — evaluate reminders, never raise into the thread."""
    try:
        # Imported lazily so the scheduler module stays cheap to import and to
        # avoid any import-time coupling with the reminders/notify stack.
        from .reminders import evaluate_and_notify
        evaluate_and_notify(force=False)
    except Exception as e:
        log_event("scheduler_job_failed", level=logging.ERROR, error=str(e))


def start_scheduler() -> None:
    """
    Start the background scheduler with the daily reminder job. Idempotent and
    disabled under tests (``AUTOLEDGER_DISABLE_SCHEDULER=1``).
    """
    global _scheduler
    if _scheduler is not None:
        return
    if os.environ.get("AUTOLEDGER_DISABLE_SCHEDULER") == "1":
        return

    # Read the configured time lazily (settings import pulls in the data layer).
    from .clock import household_tz
    from .settings import load_settings
    hh, mm = _parse_time(load_settings().get("reminder_check_time", _DEFAULT_TIME))
    # Anchor the daily time to the household timezone (v2.2.0). Without an
    # explicit zone APScheduler used the container's UTC, so "08:00" fired at
    # 09:00 local all summer.
    tz = household_tz()

    _scheduler = BackgroundScheduler(daemon=True, timezone=tz)
    _scheduler.add_job(
        _run_daily_job,
        CronTrigger(hour=hh, minute=mm, timezone=tz),
        id=_JOB_ID,
        replace_existing=True,
    )
    _scheduler.start()
    log_event("scheduler_started", at=f"{hh:02d}:{mm:02d}", tz=str(tz))


def reschedule_daily(time_str: str) -> None:
    """Move the daily job to ``HH:MM`` in the current household timezone.

    Called when either the check time or the timezone setting changes, after
    the new settings are saved, so it re-reads the zone.
    """
    if _scheduler is None:
        return
    from .clock import household_tz
    hh, mm = _parse_time(time_str)
    tz = household_tz()
    _scheduler.reschedule_job(_JOB_ID, trigger=CronTrigger(hour=hh, minute=mm, timezone=tz))
    log_event("scheduler_rescheduled", at=f"{hh:02d}:{mm:02d}", tz=str(tz))
