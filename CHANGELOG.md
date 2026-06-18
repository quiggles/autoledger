# AutoLedger — Changelog

All notable changes to this project are documented here.
Format follows [Keep a Changelog](https://keepachangelog.com/en/1.0.0/).

---

## [Unreleased]

### Fixed
- **Manually-entered fuel fills never produced an MPG figure.** `POST /api/costs`
  returned early inside the odometer branch, *before* the `is_full_tank` flag was
  assigned, so hand-entered fills were saved without it. The efficiency engine
  requires `is_full_tank`, so MPG/km-L only ever appeared for LubeLogger imports
  (which set the flag themselves). `routes/costs.py` now builds the complete entry
  before a single load → append → save. Found by the new test suite; guarded by
  `tests/test_api.py::test_reports_summary_end_to_end`.

### Added
- **pytest test suite** (`tests/`) covering the high-risk logic: date-format
  precedence, the MPG/efficiency engine, LubeLogger import, JSON export/import
  round-trip, and cost/vehicle/settings/reports endpoint validation. Runs on
  Python 3.12 in Docker via `make test` (see ADR 0005). 51 tests.
- `pyproject.toml` (pytest + ruff config) and `requirements-dev.txt`.
- `make lint` / `make fmt` now run ruff in the same Python 3.12 container.

### Changed
- Linted the codebase for the first time (ruff): import ordering, removed an
  unused import, dropped an unused loop variable, tidied an open-mode arg. No
  behavioural changes. `ruff format` deliberately not applied (would flatten the
  project's aligned-column style; `E701` ignored to keep aligned one-liners).

### Docs
- Renamed `HANDOFF.md` → `HANDOVER.md` to match the standard project doc set,
  bumped its version header to 1.8.6, and added embedded Mermaid diagrams
  (component architecture + add-a-fill request flow).
- Added `docs/adr/` with the project's first Architecture Decision Records:
  flat-JSON storage (0001), single Gunicorn worker (0002), DOM-as-source-of-truth
  / scoped element IDs (0003), and the no-test-suite-yet debt (0004).
- Added a `Makefile` with standard targets (`setup`, `run`, `test`, `lint`,
  `fmt`, `clean`).
- Removed a direct reference to the maintainer by name in the handover doc.

### Repository
- Stopped tracking macOS `.DS_Store` files (they were committed before the
  `.gitignore` rule existed) and removed them from the tree.
- Earlier housekeeping now recorded here for completeness: added `.gitignore`,
  renamed `.env` → `.env.example`, and rewrote the README install steps to be
  cross-platform (Mac / Linux / Synology) with an AI-attribution credit.

---

## [1.8.6] — 2026-05-19

### Fixed — Fuel Detail Panel (definitive root cause found)

**Root cause: duplicate HTML element IDs across two tables.**

The dashboard (`recent-body`) and the entries page (`entries-body`) both render
the same cost records using `buildRow()`. Both generated identical element IDs:
`id="panel-abc123"` and `id="expand-abc123"`.

`document.getElementById()` returns the **first** element with a given ID found
in DOM order. Since the dashboard is rendered before the entries table, clicking
Detail on the entries page toggled the dashboard's panel (hidden, zero height)
rather than the visible entries panel. The entries panel never moved.

This explained every observed symptom:
- Works on dashboard (only one table, no collision)
- Doesn't work on entries (dashboard panel found first)
- "Works on second click" was never true — the first click toggled the wrong panel

**Fix:** All IDs are now scoped to their table using a `scope` parameter:
- Dashboard: `panel-recent-{id}`, `expand-recent-{id}`
- Entries:   `panel-entries-{id}`, `expand-entries-{id}`

`buildRow(c, mpgMap, scope)` accepts the scope and embeds it in all element IDs.
`toggleFuelDetail(id, scope)` looks up `panel-${scope}-${id}` — guaranteed unique.

The `_expandedRows` Set (removed in v1.8.5) stays removed. DOM classList remains
the single source of truth for panel open/closed state.

---

## [1.8.5] — 2025

### Fixed — Fuel Detail Panel (definitive fix)
After extensive diagnosis using browser alert() dumps, the root cause of the
persistent fuel detail toggle bug was identified and fixed properly:

**Root cause:** A JavaScript `Set` called `_expandedRows` was used to track
which rows were open. Every time `innerHTML` re-rendered the table, the Set
retained stale IDs from previous renders. The toggle function checked the Set
to determine current state — but the Set and the DOM had drifted out of sync.
The first click would collapse (the Set said "open", DOM showed closed), the
second click would expand correctly.

**Fix:** The `_expandedRows` Set has been eliminated entirely. `toggleFuelDetail`
now reads current state directly from `panel.classList.contains('open')` —
the DOM is the single source of truth. This cannot drift because state is read
from the same element that displays it.

**Other improvements in this version:**
- `showPage('entries')` now calls `renderEntriesTable()` on navigation, ensuring
  the table is always fresh when switching pages
- Full code audit — every function documented with JSDoc comments
- All magic numbers and design decisions explained in code comments
- Module-level state variables consolidated and documented
- Dead code paths removed

---

## [1.7.3] — 2025

### Fixed
- **Detail button now works reliably** — `buildRow` was generating an inline
  detail row AND `toggleFuelDetail` was also inserting one via DOM, causing
  conflicts and intermittent failures. Removed inline generation entirely;
  `toggleFuelDetail` is now the sole owner of detail row creation
- **Race condition eliminated in toggleFuelDetail** — now uses cached
  `_mpgMapCache` synchronously when available. Collapse path is fully
  synchronous with no async gap where state could change
- **Cost per mile chart** — fixed calculation to use consecutive monthly
  odometer readings (last odo of prev month → last odo of current month)
  instead of min/max within a single month, which always gave 0 when only
  one fill was recorded per month

---

## [1.7.1] — 2025

### Fixed
- **Reports not rendering** — `showChartLoading` was replacing the `<canvas>`
  element's parent innerHTML with a spinner div, destroying the canvas.
  `makeChart` then found no canvas to draw on. Fixed by overlaying the spinner
  as a sibling element and hiding/showing canvas with `display` instead of
  replacing DOM nodes
- **Detail button intermittent** — `toggleFuelDetail` used `outerHTML`
  assignment on a `<tr>` inside `<tbody>`, which is unreliable across browsers.
  Replaced with proper DOM insertion: `document.createElement` + `insertBefore`
- **`showChartEmpty`** fixed by the same approach — no longer destroys canvas

### Added
- **Cost per Mile chart** — total monthly spend ÷ miles driven (requires
  odometer readings on fuel entries)
- **Fill-up Interval chart** — days between consecutive fuel stops; reveals
  changes in driving patterns (e.g. commuting vs working from home)
- **Fuel vs Other Costs chart** — monthly fuel spend overlaid with all other
  costs as a stacked area chart; shows when big services or insurance hits
- **Annual Breakdown table** — year-by-year summary with columns for each
  cost category, average MPG, and miles driven; most recent year first;
  useful for budgeting and tax records

---

## [1.7.0] — 2025

### Added
- **Collapsible fuel detail rows** — main table stays clean with Date, Category,
  Cost, Litres, Δ mi., Unit Cost, Note; clicking "▼ Detail" expands a row
  showing all fuel metrics (odometer, MPG, km/L, L/100mi, unit cost)
- **Annual comparison card** on dashboard — shows current year total vs
  previous year with coloured delta badge (green = spending less) and
  current-year monthly average
- **Skeleton loading states** — summary cards and table rows show animated
  shimmer placeholders while data loads, eliminating blank flash
- **Chart loading spinners** — each chart shows a spinner while its data
  fetches, replacing the confusing blank-then-appear behaviour
- **UK date format** — all table date columns now display DD/MM/YYYY;
  data is still stored and compared as ISO-8601 internally
- **Category remembered** between add form submissions — avoids reselecting
  the same category for rapid sequential entries
- **MPG map cached** per data load cycle — previously fetched independently
  for each table render; now fetched once and shared, halving API calls
- **Empty state on reports** — meaningful message when no data exists for
  the selected period, not just blank chart areas

### Fixed
- **Full-tank badge** colour changed from orange/fuel-red to green
  (consistent with the "success" semantic colour — green = good efficiency)
- **Vehicle switcher** now only closes on a genuine click outside the widget,
  not on any document click, eliminating the accidental-close problem
- **Stale localStorage vehicle ID** cleared when that vehicle is deleted
- **`_settingsDirty` flag** properly reset on page load to prevent false
  unsaved-changes warnings on first navigation
- **Duplicate bulk_delete function** in costs.py removed (was registered twice)
- **Gunicorn workers** reduced from 2 to 1 to prevent concurrent JSON write
  races on the flat-file storage backend
- **Atomic file writes** via `tempfile` + `os.replace()` — prevents corrupt/
  truncated JSON files if the process crashes during a write
- **`parse_date_to_iso`** consolidated into `data.py` and imported by both
  `importexport.py` and `reports.py` — previously duplicated in three places
- **`load_settings`** now uses shared `_load_json` from `data.py`
- **`report_summary`** now loads vehicle costs once and reuses the list,
  eliminating a redundant `load_data()` call
- **Table column count** corrected — `buildRow` and `<thead>` now agree on 9
  columns; mismatch was causing misaligned cells

---

## [1.6.0] — 2025

### Added
- **Odometer strip** on dashboard — shows most recent reading and date; updates after every add/edit/delete/import
- **Odometer hint** in add form — shows last recorded mileage next to the field label
- **Odometer continuity check** — server warns (non-blocking) if new reading is lower than last known
- **`GET /api/costs/last-odometer`** — returns most recent odometer and date for a vehicle
- **Sort control** on Entries page — date ↓/↑, amount ↓/↑, category A–Z
- **Enter key submits** the add form from any field
- **Unsaved settings warning** — navigating away from Settings with unsaved changes prompts confirmation
- **Vehicle notes field** — free-text per vehicle (e.g. "sold 2025"); shown on vehicle card
- **Version number** in sidebar footer
- **Favicon** — eliminates 404 in browser console
- **`.dockerignore`** — keeps Docker image lean

### Fixed
- **MPG matching uses record IDs** not fragile date+odometer string matching
- **Efficiency charts respect period selector** — all report endpoints honour `months` parameter
- **Fuel fields fully editable** in edit modal (were display-only in v1.5.x)
- **`_get_categories()` dead code** cleaned up from costs.py

---

## [1.5.0] — 2025

### Added
- **Fuel extra fields** on the add form and edit modal: litres, odometer
  (miles), full-tank toggle, auto-calculated price-per-litre display
- **Fuel stats strip** in table rows: shows litres, p/litre, MPG, km/L,
  odometer reading, and full-tank badge for any Fuel entry that has litres
- **MPG calculation** — computed between consecutive full-tank fill-ups
  using UK imperial gallons (4.54609L); shown in table rows and reports
- **Reports page** with 5 Chart.js charts:
  - Monthly spend stacked bar (by category)
  - Spend by category doughnut
  - Cumulative spend area line
  - MPG efficiency trend line
  - Price per litre trend line
- **KPI strip** on Reports page: total spend, avg/month, total litres,
  avg p/litre, avg MPG, best MPG
- **Period selector** on Reports: 3 months / 6 months / 12 months / All time
- **`routes/reports.py`** — new blueprint with 5 aggregation endpoints
- **`python-dateutil`** added to requirements for relativedelta month maths
- Sidebar widened from 220px to 260px to accommodate the logo properly

### Fixed
- Category validation on POST/PUT is now permissive — any non-empty string
  is accepted, preventing "Road Tax" and other custom categories from being
  rejected if they differ from the current session's settings list
- `GET /api/settings` now auto-merges any categories found in real cost
  records into the settings list, preventing orphaned categories after
  data imports or settings changes
- Charts correctly destroy and recreate on period change and theme toggle
  to avoid Chart.js canvas reuse errors

---

## [1.4.0] — 2025

### Added
- **Multi-vehicle support** — every cost record now carries a `vehicle_id`
- **Vehicles page** — add, edit, delete vehicles with name, make, model,
  year, colour, and registration plate; per-vehicle total cost shown on card
- **Vehicle switcher** in the sidebar — click to switch active vehicle;
  preference persisted to `localStorage`
- **No-vehicle splash** — shown on first run until at least one vehicle is added
- **`routes/vehicles.py`** — new blueprint with full CRUD; DELETE supports
  `?cascade=true` to also remove all associated cost records
- **`routes/data.py`** extended with `load_vehicles` / `save_vehicles`;
  data directory now configurable via `DATA_DIR` env var (replaces `DATA_FILE`)
- **Delete vehicle confirmation modal** — two options: delete vehicle only,
  or delete vehicle and all its costs
- **Export** now includes the full vehicles array alongside records
- **Import** merges vehicles by ID as well as cost records

### Changed
- `GET /api/costs` now accepts `?vehicle_id=` query param to filter records
- `POST /api/costs` now requires a `vehicle_id` field in the request body
- `POST /api/import/lubelogger` now requires a `vehicle_id` form field
- `docker-compose.yml` updated: `DATA_FILE` env var replaced by `DATA_DIR`
- Dashboard title and subtitle update dynamically to show the active vehicle

---

## [1.3.0] — 2025

### Added
- **Settings page** — currency symbol (12 common presets + custom) and
  cost categories (add / remove) stored server-side in `/data/settings.json`
- **Sidebar navigation** — SPA with Dashboard, Entries, Import/Export, Settings pages
- **Dynamic categories** — summary cards, filter pills, and dropdowns all
  rebuild from settings; API validation also uses live settings categories
- **Filter pills** on Entries page replace the old dropdown
- **Search bar** on Entries page filters by note text or category name
- **Row-hover actions** — Edit and Delete buttons appear on hover (cleaner default state)
- **Redesigned visual language** — Syne + Inter typefaces; indigo accent;
  left-stripe stat cards; blurred modal backdrop; refined spacing throughout

### Changed
- `routes/costs.py` now reads categories from `routes/settings.py` rather
  than a hardcoded constant — custom categories validate correctly on POST/PUT
- Summary cards are now fully dynamic (no longer hardcoded HTML)
- Category colour assignment uses CSS variable slots `--c1`…`--c6`, cycling
  for more than 6 categories

---

## [1.2.1] — 2025

### Changed
- `docker-compose.yml` now works on both Mac and Synology without manual edits
- Data path is controlled by `DATA_PATH` in the new `.env` file
- `.env` ships with `DATA_PATH=./data` (Mac default); one line change switches
  it to `/volume1/docker/autoledger/data` for Synology

---

## [1.2.0] — 2025

### Added
- **Light mode** is now the default; dark mode toggled via header button,
  preference persisted to `localStorage`
- **Edit modal** — existing records can now be edited in-place (PUT endpoint)
- **Source badges** — imported records show a small label indicating origin
  (`lubelogger`, `import`) so manually-entered and imported data are
  visually distinguished
- **`HANDOFF.md`** — developer handover document added to project root
- **`CHANGELOG.md`** — this file
- **Modular Flask structure** — routes split into `routes/costs.py` and
  `routes/importexport.py`, with shared helpers in `routes/data.py`
- **Separated CSS and JS** — `/static/css/styles.css` and `/static/js/app.js`
  replace the previous inline monolith
- **Gunicorn** added as production WSGI server (replaces Flask dev server)
- **`docker-compose.yml`** updated to Synology conventions
  (`/volume1/docker/autoledger/data`), correct restart policy
  (`unless-stopped`), and port `5050` to avoid Synology conflicts
- **Input validation** on POST and PUT — returns structured error responses
- **`DATA_FILE` environment variable** — data file path is now configurable

### Changed
- Currency symbol updated to `£` (GBP) throughout UI
- Record IDs now use UUID4 (were ISO timestamp strings in v1.0.0)
- PUT endpoint added (was missing — edits were impossible in v1.x)
- Error handling narrowed from broad `try/except` to per-operation
  exceptions so silent failures are eliminated

### Fixed
- LubeLogger importer now strips `£` as well as `$` and `,` from cost fields

---

## [1.1.0] — 2025

### Added
- Import from LubeLogger CSV (Fuel, Service, and Taxes tabs)
- Import from AutoLedger JSON (duplicate-safe, ID-matched)
- Export to AutoLedger JSON (with metadata envelope)

---

## [1.0.0] — 2025

### Added
- Initial release
- Manual cost entry (Fuel, Insurance, Servicing & Repairs, Tax & Registration)
- Per-category summary cards
- Delete entries
- Category filter on table
- Docker / Docker Compose deployment
