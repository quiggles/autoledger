# 2. Single Gunicorn worker

Date: 2026-05-20
Status: Accepted

## Context

The app serves its API through Gunicorn in the Docker image. Persistence is
whole-file JSON read-modify-write ([ADR 0001](0001-flat-json-storage.md)), which
is not safe under concurrent writers: two workers handling simultaneous POSTs
would each load the file, mutate their copy, and the second write would clobber
the first.

## Decision

Run Gunicorn with exactly one worker process. The `Dockerfile` CMD pins the
worker count to 1.

## Alternatives considered

- **Multiple workers + file locking** (`fcntl.flock`) — would allow concurrency
  but adds lock-handling complexity and cross-platform footguns for a tool that
  has a single user and negligible request volume.
- **Multiple workers + a real database** — solves it properly but pulls in the
  storage decision we explicitly deferred in ADR 0001.

## Consequences

- **Positive:** writes are naturally serialised; no locking code, no race
  conditions, no corruption. Perfectly adequate for one user.
- **Negative:** no request parallelism. A slow request blocks others. This is a
  non-issue at the expected load (one person, occasional use) but would need
  revisiting if the storage layer were upgraded and the app made multi-user.
