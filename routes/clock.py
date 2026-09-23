"""
routes/clock.py — "now" and "today" in the household's timezone
================================================================
v2.2.0  New. The container runs in UTC, and the app used ``date.today()`` /
        naive ``datetime.now()`` throughout, so:

          * the daily reminder job's "08:00" fired at 08:00 UTC, which is
            09:00 in summer (British Summer Time);
          * from 00:00 to 01:00 BST, "today" was still yesterday, so a
            reminder due today was judged not yet due, year-to-date totals
            were a day late at New Year, and a new cost defaulted to
            yesterday's date.

        Everything now asks this module, which answers in the ``timezone``
        setting (an IANA name, default Europe/London). The scheduler uses the
        same setting, and saving a new zone reschedules the live job (see
        routes/settings.py and routes/scheduler.py).
"""

from __future__ import annotations

import logging
from datetime import UTC, date, datetime
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

log = logging.getLogger(__name__)

DEFAULT_TIMEZONE = "Europe/London"


def is_valid_timezone(name: str) -> bool:
    """True if ``name`` is an IANA timezone this system knows (e.g. "Europe/London")."""
    if not name or not isinstance(name, str):
        return False
    try:
        ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError):
        return False
    return True


def household_tz() -> ZoneInfo:
    """The configured household timezone.

    Settings validate the name on save, so an unknown zone here means the
    settings file was edited by hand or is damaged. Log it loudly and fall
    back to the default rather than take the whole app down over it.
    """
    # Imported lazily: settings imports the data layer, and the scheduler
    # imports this module at start-up.
    from .settings import load_settings

    name = load_settings().get("timezone", DEFAULT_TIMEZONE)
    if is_valid_timezone(name):
        return ZoneInfo(name)
    log.error("invalid timezone %r in settings; falling back to %s", name, DEFAULT_TIMEZONE)
    return ZoneInfo(DEFAULT_TIMEZONE)


def local_now(now: datetime | None = None) -> datetime:
    """Timezone-aware current time in the household zone.

    ``now`` (aware) is for tests, so a midnight/DST boundary can be pinned.
    """
    instant = now if now is not None else datetime.now(UTC)
    if instant.tzinfo is None:
        raise ValueError("local_now() needs a timezone-aware datetime")
    return instant.astimezone(household_tz())


def local_today(now: datetime | None = None) -> date:
    """Today's date in the household zone (not the server's)."""
    return local_now(now).date()
