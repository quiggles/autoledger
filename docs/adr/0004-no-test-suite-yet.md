# 4. No automated test suite yet (known gap)

Date: 2026-06-18
Status: Superseded by [ADR 0005](0005-testing-approach.md) (suite added the same day)

> **Update:** the gap recorded below was closed shortly after it was written.
> A pytest suite now covers exactly the high-risk areas named here, and
> immediately caught a real bug (manual fuel fills never received the
> `is_full_tank` flag, so they produced no MPG). See ADR 0005.

## Context

The project standard is that non-trivial logic carries unit and integration
tests, runnable via the Makefile. AutoLedger currently has **no** automated
tests. The riskiest logic is concentrated and well understood:

- date parsing / format precedence in `routes/data.py` (DD/MM/YYYY before
  MM/DD/YYYY — getting this wrong silently corrupts MPG maths);
- the MPG / efficiency computation in `routes/reports.py`;
- the LubeLogger CSV import mapping in `routes/importexport.py`.

## Decision

Record the gap honestly rather than ship a `make test` target that pretends to
test. For now `make test` runs an import smoke check only. The first real tests
should be `pytest` units around the three functions above, since they are pure
and have known historical failure modes (negative miles, 400+ MPG from reversed
date parsing).

## Alternatives considered

- **Silently omit any `test` target** — violates the standard and hides the
  gap from the next maintainer.
- **Write the full suite now** — out of scope for the current documentation
  pass; captured here so it is not forgotten.

## Consequences

- **Positive:** the debt is visible and the highest-value test targets are
  named, so picking this up later is cheap.
- **Negative:** until the suite exists, regressions in date parsing and MPG
  maths can only be caught manually. Treat changes to `data.py` and
  `reports.py` with extra care and verify against real import data.
