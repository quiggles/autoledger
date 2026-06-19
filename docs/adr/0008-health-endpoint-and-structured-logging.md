# 8. Health endpoint, Docker HEALTHCHECK, and structured logging

Date: 2026-06-19
Status: Accepted

## Context

The project principle is "fail loud, never swallow", yet the codebase had **no
logging of any kind** — a failed save, a bad import row, or a request error left
no trace anywhere a maintainer could see. Separately, the user runs Container
Radar, Homepage (with siteMonitor) and Portainer and wanted a real
application-level health signal rather than a bare open-port check.

## Decision

**Health** — add `GET /api/health` (unauthenticated, on the auth allow-list)
returning `{status, version, vehicles, records}`. The record counts double as a
storage-readability probe: if the data files cannot be loaded the endpoint
reports `degraded` with HTTP 503. A Docker `HEALTHCHECK` polls it using Python's
`urllib` (the slim base image has no `curl`).

**Logging** — add `routes/logging_config.py`: a single stdout logger emitting
compact `key=value` records (greppable, and captured by Docker / Portainer /
Container Radar). Instrument the I/O edges that previously failed silently:
`_save_json` failures, JSON-import bad rows, malformed numeric records in
reports, auth events (onboard/login/logout/failed), notification send results,
scheduler runs, and a 500 error handler.

## Alternatives considered

- **A JSON-logging stack** (e.g. `structlog` + JSON formatter): more machine-
  parseable, but adds a dependency and ceremony for no real benefit at this
  scale. `key=value` to stdout is enough to debug a single-user tool and is
  trivially greppable.
- **TCP/port health check only** (Docker default): cheap but misleading — the
  port can be open while the app is broken. The endpoint reflects actual app +
  storage health.
- **No version in health**: rejected; exposing the version lets Container Radar /
  Homepage show what is deployed, and it is non-sensitive.

## Consequences

- **Positive:** failures now leave a structured trace; monitors get a truthful
  health signal including the running version; no new dependencies.
- **Negative:** logs go to stdout only (no file rotation) — appropriate for a
  containerised app where the platform owns log capture and rotation. `LOG_LEVEL`
  can be raised to `DEBUG` via env without a code change.
