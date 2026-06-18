# 3. The DOM is the source of truth for UI state (scoped element IDs)

Date: 2026-05-20
Status: Accepted

## Context

The same cost record is rendered in two tables: the dashboard (`recent-body`)
and the entries page (`entries-body`). An early implementation tracked which
fuel-detail panels were open in a JavaScript `Set` (`_expandedRows`) and gave
each panel an id of the form `panel-{recordId}`.

Two bugs followed:

1. **Duplicate IDs.** Because a record appears in both tables, two elements
   shared `id="panel-{recordId}"`. `document.getElementById` returns the first
   in DOM order (the dashboard's, which is hidden), so clicking "Detail" on the
   entries page toggled the wrong, invisible panel.
2. **State drift.** The `_expandedRows` Set repeatedly fell out of sync with the
   actual DOM after re-renders, producing panels that were visually open but
   logically closed (and vice-versa).

## Decision

1. **Scope every element id by its table:** `panel-recent-{id}` /
   `expand-recent-{id}` versus `panel-entries-{id}` / `expand-entries-{id}`.
   `buildRow(c, mpgMap, scope)` and `toggleFuelDetail(id, scope)` thread the
   scope through.
2. **Make the DOM the single source of truth** for open/closed state:
   `panel.classList.toggle('open')` is the only mechanism. No JS variable
   mirrors DOM state. The `_expandedRows` Set was deleted (v1.8.5).

## Alternatives considered

- **Keep a JS state object and reconcile after each render** — this is what
  caused the drift; reconciliation is exactly the bug surface we removed.
- **Render each record in only one table** — would avoid the id collision but
  the dashboard-plus-entries split is a deliberate UX feature.

## Consequences

- **Positive:** no duplicate-id ambiguity, no state-sync bugs. UI state is
  always exactly what the DOM shows.
- **Negative:** any future code that renders the same record in a third context
  must invent a new scope string and pass it consistently, or the collision
  returns. This is documented in the frontend section of `HANDOVER.md`.
