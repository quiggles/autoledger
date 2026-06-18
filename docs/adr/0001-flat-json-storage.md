# 1. Flat JSON files for storage (not a database)

Date: 2026-05-20
Status: Accepted

## Context

AutoLedger is a single-user, self-hosted vehicle cost tracker. The data set is
small (hundreds of records, not millions) and the deployment target is a home
Docker host or a Synology NAS where operational simplicity matters more than
query performance. We needed to choose a persistence layer.

## Decision

Store all state as three flat JSON files under the mounted `/data` volume:
`costs.json`, `vehicles.json`, and `settings.json`. Reads load the whole file;
writes serialise the whole structure back via an atomic temp-file-plus-`os.replace`
in `routes/data.py`.

## Alternatives considered

- **SQLite** — robust, transactional, still file-based. Rejected for now because
  it adds a schema/migration burden and makes manual inspection, diffing and
  backup harder for a data set this small.
- **Postgres/MySQL** — gross over-engineering for a single-user tool; adds a
  second container and network dependency.

## Consequences

- **Positive:** trivial to back up (copy the folder), inspect (open in any
  editor), diff, and restore. No schema migrations. Zero external services.
- **Negative:** the entire file is loaded into memory and rewritten on every
  change, so this does not scale beyond ~1000 records and concurrent writers
  would corrupt the file. The single-worker decision ([ADR 0002](0002-single-gunicorn-worker.md))
  exists specifically to make the write path safe.
- **Migration path:** if scale ever demands it, only the load/save helpers in
  `routes/data.py` need replacing with a SQLite-backed implementation; the
  blueprints are agnostic to the storage format.
