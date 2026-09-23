# 9. Household time zone as an in-app setting

Date: 2026-09-23
Status: Accepted

## Context

The container runs in UTC. Two things depended on the server's clock:

- The daily reminder job (ADR 0007) was scheduled with an APScheduler
  `CronTrigger` that had no timezone, so a configured "08:00" fired at
  08:00 UTC, which is 09:00 British Summer Time for half the year.
- Fifteen `date.today()` / naive `datetime.now()` calls made "today" the
  server's date. From 00:00 to 01:00 BST the app still thought it was
  yesterday. Reminders due today looked not yet due, new costs defaulted to
  yesterday, and year-to-date totals rolled over an hour late at New Year.

## Decision

- Add a **`timezone` setting** (an IANA name, default `Europe/London`),
  editable on the Settings page and validated with `zoneinfo` on save
  (unknown names are rejected with a 400).
- All date/time questions go through **`routes/clock.py`**: `local_today()` and
  `local_now()`, where `local_now()` is timezone-aware. Nothing else calls
  `date.today()` or naive `datetime.now()`.
- The scheduler and `reschedule_daily()` pass the zone to both the scheduler
  and the `CronTrigger`. Saving a new time **or** a new zone reschedules the
  live job at once, without a restart.
- A damaged settings file with an unknown zone logs an error and falls back
  to the default rather than stopping the app.

## Alternatives considered

- **Set `TZ=Europe/London` on the container.** It's a one-line fix, but the
  answer then depends on deployment configuration that differs between hosts
  (Mac, Synology, other Linux). It is invisible in the app, can't be changed
  by the person using it, and leaves any `date.today()` added later silently
  correct on one host and wrong on another.
- **Store everything in UTC and convert only in the browser.** This fixes
  display, but not the server-side questions: whether a reminder is due, and
  when the daily job fires.

## Consequences

- Correct across the BST/GMT boundary, pinned by `tests/test_timezone.py`
  (both sides of BST midnight, a GMT night, a non-UK zone, validation, and the
  scheduler receiving the zone).
- `created_at` / `exported_at` timestamps now carry a UTC offset
  (`…+01:00`). Existing records without one still sort correctly, because the
  only consumer (vehicle ordering) compares the date-time prefix.
- New code must use `routes/clock.py`. This is noted in HANDOVER.md.
