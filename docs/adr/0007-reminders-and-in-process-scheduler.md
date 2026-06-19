# 7. Reminders with an in-process daily scheduler and HA/email notifications

Date: 2026-06-19
Status: Accepted

## Context

AutoLedger tracks costs but had no forward-looking signal: there was nothing to
warn that an MOT, service, road tax or insurance renewal was approaching — by
date or by mileage. The user runs Home Assistant and wants those reminders both
surfaced in the UI and pushed out so they fire even when the app is closed.

Two design questions needed the architect's call:

1. **How should date-based reminders fire?** Mileage-based reminders only change
   when a fill is logged (so they can be evaluated on demand), but a date-based
   reminder needs *something* to push it when nobody has the app open.
2. **Which notification channels?**

## Decision

**Model** — reminders live in `data/reminders.json`, one record per
vehicle+type, each with an optional `due_date` and/or `due_mileage`, lead times
(`lead_days` / `lead_miles`), and optional recurrence (`recur_months` /
`recur_miles`). "Current mileage" is the highest fuel odometer for the vehicle.
Status is the worst of the date and mileage dimensions: `ok` / `due` / `overdue`.
All UI strings are human-readable ("due in 12 days", "in 350 miles").

**Firing** — an **in-process APScheduler** `BackgroundScheduler` runs a daily job
that evaluates all reminders, pushes Home Assistant sensor states, and emails a
digest of newly-due items. The UI also evaluates live on load, and a "check now"
button forces an evaluation.

**Channels** — **both** Home Assistant and email, each independently toggleable:
HA receives one `sensor.autoledger_<vehicle>_<type>` state per reminder (with
`due_date` / `due_in_days` / `due_mileage` / `miles_until` attributes) plus an
optional notify-service call; email is SMTP/STARTTLS with a "Test email" button
and inline Resend/Gmail setup help. A `last_notified` date caps external
notifications at one per reminder per day.

## Alternatives considered

- **Passive / on-demand only** (no scheduler): no new dependency, but a date-based
  reminder would never push unless the app was open — defeats the main purpose.
- **External trigger** (host cron / HA automation / Claude `/schedule` hitting an
  endpoint): works, but spreads the schedule across systems to maintain. The app
  already runs as **exactly one Gunicorn worker** (ADR 0002), which makes an
  in-process scheduler trivially correct — there is precisely one instance, so no
  multi-worker double-fire to guard against.
- **Single channel** (HA-only or email-only): rejected; the user wanted both,
  and they share the same evaluation path so building both is cheap.

## Consequences

- **Positive:** self-contained — no external cron or extra container; reminders
  fire on time; HA states are reusable in dashboards/automations; the single
  worker guarantees one scheduler with no locking.
- **Negative:** adds the `APScheduler` dependency and a background thread in the
  worker. The thread is disabled under tests (`AUTOLEDGER_DISABLE_SCHEDULER=1`).
  If the app is ever made multi-worker (see ADR 0002), the scheduler would need a
  single-instance guard (e.g. an advisory lock) to avoid duplicate fires.
- **Note:** changing the daily check time in the UI reschedules the live job
  immediately; it does not require a container restart.
