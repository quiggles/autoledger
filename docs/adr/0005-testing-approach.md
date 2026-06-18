# 5. Testing approach: pytest in a Python 3.12 container with file-isolated fixtures

Date: 2026-06-18
Status: Accepted

## Context

[ADR 0004](0004-no-test-suite-yet.md) acknowledged the absence of tests and
named the highest-risk logic (date parsing, MPG maths, LubeLogger import). We
now add the suite. Two constraints shaped the approach:

1. **The app targets Python 3.12** (`Dockerfile`) and uses 3.10+ syntax
   (`X | None` unions evaluated at definition time). The development Mac only
   has the system Python 3.9, on which the code cannot even be imported.
2. **Persistence is flat JSON files** whose paths are resolved from `DATA_DIR`
   at import time. Tests must not touch the real `/data` volume, and each test
   needs a pristine store.

## Decision

- **Run tests inside an ephemeral `python:3.12-slim` container** with the source
  bind-mounted (`make test`). This matches production exactly and removes any
  dependency on the host's Python version.
- **Use `pytest` + the Flask test client.** No live server, no HTTP stack.
- **Isolate storage in `tests/conftest.py`:** set `DATA_DIR` to a temp directory
  *before* the app is imported, then wipe the three JSON files before and after
  every test (an autouse fixture). This gives hermetic tests against the real
  storage code path without mocking the file layer.
- **Cover the named risk areas plus endpoint behaviour:** `parse_date_to_iso`
  format precedence, `_compute_efficiency` (pairing, sanity bounds, cutoff),
  LubeLogger detection/mapping, JSON export/import round-trip, and cost/vehicle/
  settings validation via the test client.

## Alternatives considered

- **Run on the host's Python 3.9** — impossible without rewriting the type
  annotations; also wouldn't match production.
- **A local virtualenv with a newer Python** — the Mac has no Python ≥3.10
  installed; mandating one adds setup friction the Docker approach avoids.
- **Mock the filesystem** (e.g. `pyfakefs`) — unnecessary complexity; a temp
  directory plus per-test cleanup exercises the genuine I/O code for free.

## Consequences

- **Positive:** tests run on the production interpreter, are fully isolated,
  and need no host Python. The suite paid for itself immediately by surfacing
  the `is_full_tank` MPG bug. `make lint` / `make fmt` follow the same
  container pattern.
- **Negative:** `make test` requires Docker running and pays a few seconds of
  container start + `pip install` per run. Acceptable for a Docker-first
  project; a CI cache or a dedicated test image could remove it later if needed.
- **Note:** `ruff format` is intentionally *not* run across the existing code,
  which uses a deliberate aligned-column style the formatter would flatten.
  `make fmt` is available for opt-in use; `E701` is ignored in `pyproject.toml`
  to permit the project's short aligned one-line conditionals.
