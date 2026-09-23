"""
Tests for the household-timezone handling added in v2.2.0.

The container runs in UTC. Before v2.2.0 "today" was the server's date (a day
behind from 00:00 to 01:00 BST) and the daily reminder job's "08:00" meant
08:00 UTC (09:00 BST). These tests pin both sides of the BST midnight hour, the
setting's validation, and that the scheduler job carries the configured zone.
"""

from __future__ import annotations

from datetime import UTC, date, datetime

import pytest

from routes import clock, scheduler
from routes.settings import DEFAULT_SETTINGS

# ── local_today / local_now ───────────────────────────────────────────────────


def test_default_timezone_is_london():
    assert DEFAULT_SETTINGS["timezone"] == "Europe/London"


def test_local_today_just_after_bst_midnight_is_already_tomorrow(client):
    # 23:30 UTC on 22 Sep = 00:30 BST on 23 Sep.
    assert clock.local_today(datetime(2026, 9, 22, 23, 30, tzinfo=UTC)) == date(2026, 9, 23)


def test_local_today_just_before_bst_midnight_is_still_today(client):
    assert clock.local_today(datetime(2026, 9, 22, 22, 30, tzinfo=UTC)) == date(2026, 9, 22)


def test_local_today_in_gmt_matches_utc(client):
    assert clock.local_today(datetime(2026, 1, 15, 23, 30, tzinfo=UTC)) == date(2026, 1, 15)


def test_local_now_is_timezone_aware(client):
    assert clock.local_now().tzinfo is not None


def test_naive_datetime_is_refused(client):
    with pytest.raises(ValueError):
        clock.local_now(datetime(2026, 9, 22, 23, 30))


def test_local_today_follows_the_setting(client):
    client.post("/api/settings", json={"timezone": "Pacific/Auckland"})
    try:
        # 12:30 UTC on 22 Sep is already 23 Sep 00:30 in Auckland (NZST, +12).
        assert clock.local_today(datetime(2026, 9, 22, 12, 30, tzinfo=UTC)) == date(2026, 9, 23)
    finally:
        client.post("/api/settings", json={"timezone": "Europe/London"})


# ── The setting ───────────────────────────────────────────────────────────────


def test_settings_default_includes_timezone(client):
    assert client.get("/api/settings").get_json()["timezone"] == "Europe/London"


def test_settings_rejects_unknown_timezone(client):
    rv = client.post("/api/settings", json={"timezone": "Mars/Olympus_Mons"})
    assert rv.status_code == 400
    assert "timezone" in rv.get_json()["error"].lower()
    assert client.get("/api/settings").get_json()["timezone"] == "Europe/London"


def test_invalid_zone_in_file_falls_back_and_logs(client, monkeypatch, caplog):
    monkeypatch.setattr(
        "routes.settings.load_settings", lambda: {**DEFAULT_SETTINGS, "timezone": "Nope/Nope"}
    )
    assert str(clock.household_tz()) == "Europe/London"
    assert any("invalid timezone" in r.getMessage() for r in caplog.records)


# ── Scheduler ─────────────────────────────────────────────────────────────────


class _FakeScheduler:
    """Captures what reschedule_daily() asks APScheduler for."""

    def __init__(self):
        self.trigger = None

    def reschedule_job(self, job_id, trigger):
        self.trigger = trigger


def test_changing_timezone_reschedules_job_in_that_zone(client, monkeypatch):
    fake = _FakeScheduler()
    monkeypatch.setattr(scheduler, "_scheduler", fake)
    client.post("/api/settings", json={"timezone": "America/New_York", "reminder_check_time": "07:15"})
    try:
        assert fake.trigger is not None
        assert str(fake.trigger.timezone) == "America/New_York"
        fields = {f.name: str(f) for f in fake.trigger.fields}
        assert fields["hour"] == "7" and fields["minute"] == "15"
    finally:
        client.post("/api/settings", json={"timezone": "Europe/London", "reminder_check_time": "08:00"})


def test_unchanged_settings_do_not_reschedule(client, monkeypatch):
    fake = _FakeScheduler()
    monkeypatch.setattr(scheduler, "_scheduler", fake)
    client.post("/api/settings", json={"currency_symbol": "£"})
    assert fake.trigger is None
