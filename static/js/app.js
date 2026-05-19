/**
 * AutoLedger — app.js  v1.8.5
 * ============================
 *
 * Architecture notes for future maintainers:
 * ─────────────────────────────────────────
 * FUEL DETAIL PANEL
 *   Each fuel row contains a hidden <div class="fuel-detail-panel"> inside
 *   its note cell. Clicking "▼ Detail" toggles the CSS class "open" on that
 *   div — which is the SOLE source of truth for open/closed state.
 *
 *   Previous versions used a JavaScript Set (_expandedRows) to track state,
 *   causing persistent sync bugs between the Set and the DOM. That Set is
 *   gone. toggleFuelDetail() reads current state directly from the element's
 *   classList, so it can never be out of sync.
 *
 * ASYNC TABLE RENDERING
 *   Both renderRecentTable() and renderEntriesTable() are async because they
 *   await getMpgMap(). getMpgMap() is cached after the first call and returns
 *   instantly on subsequent calls (still async, but resolved immediately).
 *
 * MPG CACHE
 *   _mpgMapCache is set to null whenever costs change. The next call to
 *   getMpgMap() re-fetches from the API. This means MPG data is always fresh
 *   after any add/edit/delete/import operation.
 *
 * Changelog: see CHANGELOG.md
 * v1.8.5 — Eliminated _expandedRows Set; CSS class is now sole source of truth
 *           for fuel detail panel open/closed state. Fixes persistent toggle
 *           bug on entries page. Full code audit and comment pass.
 */

'use strict';

// ── Module-level state ────────────────────────────────────────────────────────
// Keep all mutable state here so it's easy to audit.

let vehicles        = [];   // all vehicle records from API
let costs           = [];   // cost records for the active vehicle
let settings        = {     // user preferences (currency, categories)
  currency_symbol: '£',
  categories: ['Fuel', 'Insurance', 'Servicing & Repairs', 'Tax & Registration'],
};
let activeVehicleId = null; // currently selected vehicle ID
let activeFilter    = '';   // active category filter on entries page ('' = all)
let _editingId      = null; // ID of the cost record currently open in edit modal
let _deletingVehicleId = null; // ID of vehicle currently being deleted
let _isFullTank     = false; // state of the full-tank toggle on the add form
let _editIsFullTank = false; // state of the full-tank toggle on the edit modal
let _reportPeriod   = 12;   // months shown in reports (0 = all time)
let _charts         = {};   // Chart.js instances keyed by canvas ID
let _settingsDirty  = false; // true when settings have unsaved changes
let _mpgMapCache    = null;  // null = needs fetching; {} = fetched (even if empty)
let _lastCategory   = '';    // last category used in add form (remembered for next entry)
let _dropdownOpen   = false; // vehicle switcher dropdown state
let _editingVehicleId = null; // vehicle being edited in the vehicle form

const CAT_COLOURS       = ['c1', 'c2', 'c3', 'c4', 'c5', 'c6'];
const LITRES_PER_GALLON = 4.54609; // UK imperial gallon

// ── Category colour helpers ───────────────────────────────────────────────────

function catColourIndex(cat) {
  const i = settings.categories.indexOf(cat);
  return i >= 0 ? i % CAT_COLOURS.length : 0;
}
function catColourVar(cat) {
  return `var(--${CAT_COLOURS[catColourIndex(cat)]})`;
}

// ── Date formatting ───────────────────────────────────────────────────────────

/**
 * Convert ISO-8601 date (YYYY-MM-DD) → UK display format (DD/MM/YYYY).
 * Data is always stored as ISO internally; this is display-only.
 */
function fmtDate(iso) {
  if (!iso || iso.length < 10) return iso || '—';
  const [y, m, d] = iso.split('-');
  return `${d}/${m}/${y}`;
}

// ── Navigation ────────────────────────────────────────────────────────────────

/**
 * Switch to a named page. Warns if navigating away from Settings with
 * unsaved changes. Triggers page-specific refresh logic.
 */
function showPage(name) {
  // Always show vehicles page if no vehicles exist yet
  if (vehicles.length === 0 && name !== 'vehicles') name = 'vehicles';

  // Warn on unsaved settings
  if (_settingsDirty &&
      document.getElementById('page-settings').classList.contains('active')) {
    if (!confirm('You have unsaved settings changes. Leave without saving?')) return;
    _settingsDirty = false;
  }

  document.querySelectorAll('.page').forEach(p => p.classList.remove('active'));
  document.querySelectorAll('.nav-item').forEach(n => n.classList.remove('active'));
  document.getElementById(`page-${name}`).classList.add('active');
  document.getElementById(`nav-${name}`).classList.add('active');
  closeVehicleDropdown();

  // Page-specific side effects
  if (name === 'settings') renderSettingsUI();
  if (name === 'vehicles') renderVehicleGrid();
  if (name === 'reports')  loadReports();

  // Re-render the entries table when navigating to it, so it's always fresh
  // and panel state is clean. This also handles the case where data changed
  // while on another page.
  if (name === 'entries') renderEntriesTable();
}

// ── Theme ─────────────────────────────────────────────────────────────────────

function initTheme() {
  const saved = localStorage.getItem('autoledger-theme');
  if (saved === 'dark') applyTheme(true);
}

function toggleTheme() {
  const isDark = document.documentElement.classList.toggle('dark');
  localStorage.setItem('autoledger-theme', isDark ? 'dark' : 'light');
  applyTheme(isDark);
  // Redraw charts so they pick up new CSS colour variables
  if (document.getElementById('page-reports').classList.contains('active')) {
    loadReports();
  }
}

function applyTheme(isDark) {
  if (isDark) document.documentElement.classList.add('dark');
  else        document.documentElement.classList.remove('dark');
  document.getElementById('theme-icon').textContent  = isDark ? '☀' : '☾';
  document.getElementById('theme-label').textContent = isDark ? 'Light mode' : 'Dark mode';
}

// ── Bootstrap ─────────────────────────────────────────────────────────────────

async function init() {
  await loadSettings();
  await loadVehicles();

  // Restore last active vehicle from localStorage
  const saved = localStorage.getItem('autoledger-vehicle');
  if (saved && vehicles.find(v => v.id === saved)) activeVehicleId = saved;
  else if (vehicles.length > 0) activeVehicleId = vehicles[0].id;

  showSummarySkeletons(); // show placeholders immediately
  await loadCosts();
  _mpgMapCache = null;
  renderVehicleSwitcher();
  renderAll();

  if (vehicles.length === 0) showPage('vehicles');
  else loadOdometer();
}

// ── Skeleton loaders ──────────────────────────────────────────────────────────

/** Show animated placeholder cards in the summary grid while data loads. */
function showSummarySkeletons() {
  const grid = document.getElementById('summary-grid');
  if (!grid) return;
  grid.innerHTML = Array(5).fill(0)
    .map(() => `<div class="skeleton skeleton-card"></div>`)
    .join('');
}

// ── Odometer strip ────────────────────────────────────────────────────────────

/**
 * Fetch the most recent odometer reading for the active vehicle and
 * display it in the dashboard header strip.
 * Also updates the hint text next to the odometer field in the add form.
 */
async function loadOdometer() {
  if (!activeVehicleId) return;
  try {
    const r = await fetch(`/api/costs/last-odometer?vehicle_id=${activeVehicleId}`);
    if (!r.ok) return;
    const d = await r.json();
    const strip = document.getElementById('odometer-strip');
    if (d.odometer) {
      document.getElementById('odo-reading').textContent =
        Math.round(d.odometer).toLocaleString();
      document.getElementById('odo-date').textContent = fmtDate(d.date) || '—';
      strip.style.display = 'flex';
      const hint = document.getElementById('odo-hint');
      if (hint) hint.textContent = `last: ${Math.round(d.odometer).toLocaleString()} mi`;
    } else {
      strip.style.display = 'none';
    }
  } catch (e) { /* non-critical — silent fail */ }
}

// ── Vehicle switcher ──────────────────────────────────────────────────────────

function renderVehicleSwitcher() {
  const active = vehicles.find(v => v.id === activeVehicleId);
  document.getElementById('vs-avatar').textContent =
    active ? active.name[0].toUpperCase() : '?';
  document.getElementById('vs-name').textContent =
    active ? active.name : 'Select vehicle';
  document.getElementById('vs-reg').textContent =
    active ? (active.registration || active.make || '—') : '—';

  const dd = document.getElementById('vs-dropdown');
  dd.innerHTML = vehicles.length === 0
    ? `<div style="padding:0.75rem;font-size:0.75rem;color:var(--muted);text-align:center">
         No vehicles yet
       </div>`
    : vehicles.map(v => `
        <button class="vs-option ${v.id === activeVehicleId ? 'active' : ''}"
                onclick="selectVehicle('${v.id}')">
          <div class="vs-avatar">${v.name[0].toUpperCase()}</div>
          <div class="vs-info">
            <span class="vs-name">${v.name}</span>
            <span class="vs-reg">${v.registration || v.make || '—'}</span>
          </div>
        </button>`).join('');
}

function toggleVehicleDropdown() {
  _dropdownOpen = !_dropdownOpen;
  document.getElementById('vs-dropdown').classList.toggle('open', _dropdownOpen);
  document.querySelector('.vs-caret').classList.toggle('open', _dropdownOpen);
}

function closeVehicleDropdown() {
  _dropdownOpen = false;
  document.getElementById('vs-dropdown').classList.remove('open');
  document.querySelector('.vs-caret')?.classList.remove('open');
}

async function selectVehicle(id) {
  activeVehicleId = id;
  localStorage.setItem('autoledger-vehicle', id);
  closeVehicleDropdown();
  _mpgMapCache = null;
  showSummarySkeletons();
  await loadCosts();
  renderVehicleSwitcher();
  renderAll();
  updateDashboardTitle();
  loadOdometer();
}

function updateSplash() {
  if (vehicles.length === 0) showPage('vehicles');
}

// ── Data loading ──────────────────────────────────────────────────────────────

async function loadSettings() {
  try {
    const r = await fetch('/api/settings');
    if (r.ok) settings = await r.json();
  } catch (e) { console.warn('Settings load failed:', e); }
}

async function loadVehicles() {
  try {
    const r = await fetch('/api/vehicles');
    if (r.ok) vehicles = await r.json();
  } catch (e) { console.warn('Vehicles load failed:', e); }
}

async function loadCosts() {
  if (!activeVehicleId) { costs = []; return; }
  try {
    const r = await fetch(`/api/costs?vehicle_id=${activeVehicleId}`);
    if (r.ok) costs = await r.json();
  } catch (e) { console.warn('Costs load failed:', e); }
}

/**
 * Re-render all dynamic UI sections after any data change.
 * Invalidates the MPG cache so efficiency data is always fresh.
 */
function renderAll() {
  updateDashboardTitle();
  renderSummaryCards();
  renderAnnualComparison();
  renderCategoryDropdowns();
  renderFilterPills();
  _mpgMapCache = null; // invalidate so next render fetches fresh MPG data
  renderRecentTable();
  renderEntriesTable();
}

// ── Dashboard title ───────────────────────────────────────────────────────────

function updateDashboardTitle() {
  const active = vehicles.find(v => v.id === activeVehicleId);
  const title  = document.getElementById('dashboard-title');
  const sub    = document.getElementById('dashboard-sub');
  if (active) {
    title.textContent = active.name;
    const parts = [active.make, active.model, active.year].filter(Boolean);
    sub.textContent   = parts.length ? parts.join(' ') : 'Car running costs';
  } else {
    title.textContent = 'Dashboard';
    sub.textContent   = 'Select a vehicle to get started';
  }
}

// ── Annual comparison card ────────────────────────────────────────────────────

/**
 * Renders a year-vs-year spend comparison on the dashboard.
 * Green delta = spending less this year. Red = spending more.
 * Hidden entirely if no data exists for either year.
 */
function renderAnnualComparison() {
  const container = document.getElementById('annual-card');
  if (!container) return;

  const thisYear  = new Date().getFullYear();
  const lastYear  = thisYear - 1;
  const sumYear   = yr => costs
    .filter(c => c.date && c.date.startsWith(String(yr)))
    .reduce((s, c) => s + parseFloat(c.amount || 0), 0);

  const thisTotal = sumYear(thisYear);
  const lastTotal = sumYear(lastYear);
  const sym       = settings.currency_symbol;

  if (lastTotal === 0 && thisTotal === 0) {
    container.style.display = 'none';
    return;
  }
  container.style.display = 'flex';

  let deltaHtml = '';
  if (lastTotal > 0) {
    const pct   = ((thisTotal - lastTotal) / lastTotal * 100).toFixed(1);
    const isUp  = thisTotal > lastTotal;
    const cls   = isUp ? 'up' : (thisTotal < lastTotal ? 'down' : 'flat');
    const arrow = isUp ? '↑' : (thisTotal < lastTotal ? '↓' : '→');
    deltaHtml   = `<span class="annual-delta ${cls}">${arrow} ${Math.abs(pct)}% vs ${lastYear}</span>`;
  }

  const monthlyAvg = (thisTotal / Math.max(new Date().getMonth() + 1, 1)).toFixed(2);

  container.innerHTML = `
    <div>
      <div class="annual-label">${thisYear} so far</div>
      <div class="annual-value">${sym}${thisTotal.toFixed(2)} ${deltaHtml}</div>
    </div>
    <div class="annual-divider"></div>
    <div>
      <div class="annual-label">${lastYear} total</div>
      <div class="annual-value">${sym}${lastTotal.toFixed(2)}</div>
    </div>
    <div class="annual-divider"></div>
    <div>
      <div class="annual-label">Monthly avg (${thisYear})</div>
      <div class="annual-value">${sym}${monthlyAvg}</div>
    </div>`;
}

// ── Summary cards ─────────────────────────────────────────────────────────────

function renderSummaryCards() {
  const grid = document.getElementById('summary-grid');
  if (!grid) return;
  const sym   = settings.currency_symbol;
  const total = costs.reduce((s, c) => s + parseFloat(c.amount || 0), 0);
  const ICONS = ['⛽', '🛡️', '🔧', '🏛️', '📦', '💡'];

  const totalCard = `
    <div class="stat-card total">
      <span class="stat-icon">💰</span>
      <div class="stat-label">Total Spent</div>
      <div class="stat-amount"><span class="stat-currency">${sym}</span>${total.toFixed(2)}</div>
    </div>`;

  const catCards = settings.categories.map((cat, i) => {
    const t = costs
      .filter(c => c.category === cat)
      .reduce((s, c) => s + parseFloat(c.amount || 0), 0);
    return `
      <div class="stat-card ${CAT_COLOURS[i % CAT_COLOURS.length]}">
        <span class="stat-icon">${ICONS[i % ICONS.length]}</span>
        <div class="stat-label">${cat}</div>
        <div class="stat-amount"><span class="stat-currency">${sym}</span>${t.toFixed(2)}</div>
      </div>`;
  }).join('');

  grid.innerHTML = totalCard + catCards;
}

// ── Category dropdowns ────────────────────────────────────────────────────────

/**
 * Rebuild the category <select> elements from current settings.
 * Preserves the current selection where possible.
 * Also restores the last-used category on the add form.
 */
function renderCategoryDropdowns() {
  ['cat', 'edit-cat'].forEach(id => {
    const sel = document.getElementById(id);
    if (!sel) return;
    const cur = sel.value;
    sel.innerHTML = settings.categories
      .map(c => `<option value="${c}">${c}</option>`)
      .join('');
    const restore = cur || (id === 'cat' ? _lastCategory : '');
    if (settings.categories.includes(restore)) sel.value = restore;
  });

  ['amount-label', 'edit-amount-label'].forEach(id => {
    const el = document.getElementById(id);
    if (el) el.textContent = `Amount (${settings.currency_symbol})`;
  });

  // Keep fuel-field visibility in sync with the current category selection
  onCategoryChange();
}

// ── Filter pills ──────────────────────────────────────────────────────────────

function renderFilterPills() {
  const c = document.getElementById('filter-pills');
  if (!c) return;
  c.innerHTML = ['', ...settings.categories].map(cat => {
    const active = activeFilter === cat ? 'active' : '';
    return `<button class="filter-pill ${active}"
                    onclick="setFilter('${cat}')">${cat || 'All'}</button>`;
  }).join('');
}

function setFilter(cat) {
  activeFilter = cat;
  renderFilterPills();
  renderEntriesTable();
}

// ── MPG map ───────────────────────────────────────────────────────────────────

/**
 * Fetch the efficiency series from the API and return a lookup map:
 *   map[recordId]           → MPG value
 *   map[recordId + '_kpl']  → km/L value
 *   map[recordId + '_miles']→ miles driven since previous fill
 *
 * Result is cached in _mpgMapCache. Cache is invalidated (set to null)
 * whenever the costs array changes. This means the API is only called
 * once per data load cycle regardless of how many tables render.
 */
async function getMpgMap() {
  if (_mpgMapCache !== null) return _mpgMapCache;
  if (!activeVehicleId) { _mpgMapCache = {}; return {}; }
  try {
    const r = await fetch(
      `/api/reports/efficiency?vehicle_id=${activeVehicleId}&months=0`
    );
    if (!r.ok) { _mpgMapCache = {}; return {}; }

    const data = await r.json();
    const map  = {};

    data.forEach(e => {
      if (e.id) {
        // v1.6.0+ records include the ID directly — reliable match
        if (e.mpg)   map[e.id]                = e.mpg;
        if (e.kpl)   map[`${e.id}_kpl`]       = e.kpl;
        if (e.miles) map[`${e.id}_miles`]      = e.miles;
      } else {
        // Fallback for older records: match by date + odometer
        const match = costs.find(c =>
          c.category === 'Fuel' &&
          c.date     === e.date &&
          c.is_full_tank &&
          c.odometer &&
          Math.abs(parseFloat(c.odometer) - e.odometer) < 1
        );
        if (match) {
          if (e.mpg)   map[match.id]            = e.mpg;
          if (e.kpl)   map[`${match.id}_kpl`]   = e.kpl;
          if (e.miles) map[`${match.id}_miles`]  = e.miles;
        }
      }
    });

    _mpgMapCache = map;
    return map;
  } catch (e) {
    _mpgMapCache = {};
    return {};
  }
}

// ── Fuel detail data ──────────────────────────────────────────────────────────

/**
 * Extract display-ready fuel metrics for a cost record.
 * Returns null for non-Fuel records.
 * Prefers stored values (from LubeLogger import) over calculated ones.
 */
function fuelData(c, mpgMap) {
  if (c.category !== 'Fuel') return null;

  const litres   = c.litres   ? parseFloat(c.litres)   : null;
  const odo      = c.odometer ? parseFloat(c.odometer) : null;
  const amount   = parseFloat(c.amount);

  // Efficiency from MPG map (consecutive full-tank calculation)
  const delta = mpgMap[`${c.id}_miles`] || null;
  const mpg   = mpgMap[c.id]            || null;
  const kpl   = mpgMap[`${c.id}_kpl`]   || null;

  // L/100mi: prefer stored fuel_economy (from LubeLogger), fall back to calculated
  let economy = null;
  if (c.fuel_economy && parseFloat(c.fuel_economy) > 0) {
    economy = parseFloat(c.fuel_economy).toFixed(3);
  } else if (litres && delta && delta > 0) {
    economy = ((litres / delta) * 100).toFixed(3);
  }

  // Price per litre: prefer stored unit_cost, fall back to amount/litres
  let unitCost = null;
  if (c.unit_cost && parseFloat(c.unit_cost) > 0) {
    unitCost = parseFloat(c.unit_cost).toFixed(3);
  } else if (litres && litres > 0 && amount > 0) {
    unitCost = (amount / litres).toFixed(3);
  }

  return { litres, odo, delta, mpg, kpl, economy, unitCost };
}

// ── Table row builder ─────────────────────────────────────────────────────────

/**
 * Build a single <tr> HTML string for a cost record.
 *
 * FUEL DETAIL PANEL DESIGN
 * ─────────────────────────
 * The fuel detail panel is a <div class="fuel-detail-panel"> embedded inside
 * the note <td> of the SAME row. It is always rendered in the HTML (so the
 * browser knows about it from the start), but hidden via CSS (display:none).
 *
 * Toggling is done purely by adding/removing the "open" CSS class on the
 * panel div. No JavaScript state variable tracks whether it's open —
 * toggleFuelDetail() reads the current class from the element itself.
 *
 * This avoids the long-standing sync bug where a JS Set and the DOM got
 * out of step after re-renders.
 *
 * @param {object} c       - cost record
 * @param {object} mpgMap  - MPG lookup map from getMpgMap()
 */
/**
 * Build a single table row HTML string.
 *
 * CRITICAL — TABLE SCOPE PARAMETER
 * The same cost record can appear in BOTH the dashboard (recent-body) and
 * the entries page (entries-body). If both tables use the same element IDs
 * (e.g. panel-abc123), document.getElementById finds whichever appears first
 * in the DOM — usually the dashboard's hidden panel — and toggles that instead
 * of the visible entries panel. This was the root cause of the Detail toggle
 * not working on the entries page.
 *
 * Solution: prefix all IDs with the table scope ('recent' or 'entries').
 *   Dashboard panel: id="panel-recent-abc123"
 *   Entries panel:   id="panel-entries-abc123"
 * toggleFuelDetail() receives the scope and looks up the correct element.
 *
 * @param {object} c      - cost record
 * @param {object} mpgMap - MPG lookup map from getMpgMap()
 * @param {string} scope  - 'recent' | 'entries' — scopes element IDs to table
 */
function buildRow(c, mpgMap = {}, scope = 'entries') {
  const sym      = settings.currency_symbol;
  const colour   = catColourVar(c.category);
  const isFuel   = c.category === 'Fuel';
  const fd       = isFuel ? fuelData(c, mpgMap) : null;

  // Source badge (shown for lubelogger/import records)
  const srcTag   = (c.source && c.source !== 'manual')
    ? `<span class="source-tag">${c.source}</span>` : '';

  // Full-tank badge — green, shown only for full fill-ups
  const fullBadge = (isFuel && c.is_full_tank)
    ? `<span class="full-badge">Full</span>` : '';

  // ── Note cell with embedded fuel detail panel ────────────────────────────
  // The panel is always in the DOM but hidden. CSS class "open" shows it.
  // State is read from the element — never from a JS variable.
  let noteCell;
  if (isFuel && fd) {
    const sym_ = sym; // capture for template
    const items = [
      { label: 'Odometer',  value: fd.odo      ? `${Math.round(fd.odo).toLocaleString()} mi` : '—' },
      { label: 'Litres',    value: fd.litres    ? `${fd.litres.toFixed(2)} L`                 : '—' },
      { label: '\u0394 Miles', value: fd.delta  ? `${Math.round(fd.delta)} mi`                : '—' },
      { label: 'L/100mi',   value: fd.economy   || '—' },
      { label: 'MPG',       value: fd.mpg       ? `${fd.mpg.toFixed(1)} mpg`    : '—', hi: !!fd.mpg },
      { label: 'km/L',      value: fd.kpl       ? `${fd.kpl.toFixed(2)} km/L`   : '—', hi: !!fd.kpl },
      { label: 'Unit Cost', value: fd.unitCost  ? `${sym_}${fd.unitCost}/L`      : '—' },
    ].map(it =>
      `<div class="fuel-detail-item">
         <span class="fuel-detail-label">${it.label}</span>
         <span class="fuel-detail-value ${it.hi ? 'highlight' : ''}">${it.value}</span>
       </div>`
    ).join('');

    noteCell = `
      <td class="note-cell">
        <div class="note-text">${c.note || '—'}</div>
        <div class="fuel-detail-panel" id="panel-${scope}-${c.id}">${items}</div>
      </td>`;
  } else {
    noteCell = `<td class="note-cell">${c.note || '—'}</td>`;
  }

  // ── Expand button ────────────────────────────────────────────────────────
  // Only shown for fuel rows. Reads/writes "open" class on the panel div.
  const expandBtn = (isFuel && fd)
    ? `<button class="fuel-expand-btn"
               id="expand-${scope}-${c.id}"
               onclick="toggleFuelDetail('${c.id}', '${scope}')">▼ Detail</button>`
    : '';

  return `
    <tr id="row-${scope}-${c.id}">
      <td class="date-cell">${fmtDate(c.date)}</td>
      <td>
        <div class="cat-cell">
          <span class="cat-dot" style="background:${colour}"></span>
          ${c.category}${srcTag}${fullBadge}
        </div>
      </td>
      <td class="amount-cell">${sym}${parseFloat(c.amount).toFixed(2)}</td>
      <td class="note-cell">${isFuel && fd && fd.litres ? `${fd.litres.toFixed(2)}L` : '—'}</td>
      <td class="note-cell">${isFuel && fd && fd.delta  ? `${Math.round(fd.delta)} mi` : '—'}</td>
      <td class="note-cell">${isFuel && fd && fd.unitCost ? `${sym}${fd.unitCost}` : '—'}</td>
      ${noteCell}
      <td style="white-space:nowrap">${expandBtn}</td>
      <td>
        <div class="row-actions">
          <button class="btn btn-ghost btn-sm" onclick="openEditModal('${c.id}')">Edit</button>
          <button class="btn btn-danger-ghost" onclick="deleteEntry('${c.id}')">✕</button>
        </div>
      </td>
    </tr>`;
}

// ── Fuel detail toggle ────────────────────────────────────────────────────────

/**
 * Toggle the fuel detail panel for a row.
 *
 * SCOPE PARAMETER (critical — see buildRow docs)
 * Element IDs are prefixed with the table scope to prevent collisions between
 * the dashboard (recent) and entries tables. Always pass the same scope that
 * was used when the row was built.
 *
 * State is read from panel.classList — the DOM is the single source of truth.
 * No JS variable mirrors open/closed state. This cannot drift out of sync.
 *
 * @param {string} id    - cost record ID
 * @param {string} scope - 'recent' | 'entries' — must match the table that rendered the row
 */
function toggleFuelDetail(id, scope = 'entries') {
  const panel = document.getElementById(`panel-${scope}-${id}`);
  const btn   = document.getElementById(`expand-${scope}-${id}`);
  if (!panel) return;

  // classList.toggle returns true if class was added (now open), false if removed (now closed)
  const isNowOpen = panel.classList.toggle('open');

  if (btn) {
    btn.textContent = isNowOpen ? '▲ Less' : '▼ Detail';
    btn.classList.toggle('open', isNowOpen);
  }
}

// ── Table renderers ───────────────────────────────────────────────────────────

/**
 * Render the 5 most recent entries on the dashboard.
 * Awaits MPG map so fuel stats are populated on first render.
 */
async function renderRecentTable() {
  const body = document.getElementById('recent-body');
  if (!body) return;

  const recent = [...costs]
    .sort((a, b) => b.date.localeCompare(a.date))
    .slice(0, 5);

  if (recent.length === 0) {
    body.innerHTML = `
      <tr><td colspan="9">
        <div class="empty-state">
          <span class="empty-icon">🚗</span>
          <div class="empty-title">No entries yet</div>
          <div class="empty-sub">Add your first cost above</div>
        </div>
      </td></tr>`;
    return;
  }

  const mpgMap = await getMpgMap();
  body.innerHTML = recent.map(c => buildRow(c, mpgMap, 'recent')).join('');
}

/**
 * Render the full entries table, applying category filter, search, and sort.
 * Called on: initial render, filter change, search, sort change, page nav.
 */
async function renderEntriesTable() {
  const body = document.getElementById('entries-body');
  if (!body) return;

  const search  = (document.getElementById('search-input')?.value || '').toLowerCase();
  const sortVal = document.getElementById('sort-select')?.value || 'date-desc';

  // Apply filter and search
  let filtered = costs.filter(c => {
    const matchCat    = !activeFilter || c.category === activeFilter;
    const matchSearch = !search ||
      (c.note || '').toLowerCase().includes(search) ||
      c.category.toLowerCase().includes(search);
    return matchCat && matchSearch;
  });

  // Apply sort
  const [sortField, sortDir] = sortVal.split('-');
  filtered.sort((a, b) => {
    let va, vb;
    if (sortField === 'amount') {
      va = parseFloat(a.amount || 0);
      vb = parseFloat(b.amount || 0);
    } else if (sortField === 'category') {
      va = a.category || '';
      vb = b.category || '';
    } else {
      va = a.date || '';
      vb = b.date || '';
    }
    if (va < vb) return sortDir === 'asc' ? -1 : 1;
    if (va > vb) return sortDir === 'asc' ?  1 : -1;
    return 0;
  });

  if (filtered.length === 0) {
    body.innerHTML = `
      <tr><td colspan="9">
        <div class="empty-state">
          <span class="empty-icon">${search ? '🔍' : '🚗'}</span>
          <div class="empty-title">${search ? 'No matching entries' : 'No entries yet'}</div>
          <div class="empty-sub">${search ? 'Try a different search' : 'Add your first cost on the Dashboard'}</div>
        </div>
      </td></tr>`;
    return;
  }

  const mpgMap = await getMpgMap();
  body.innerHTML = filtered.map(c => buildRow(c, mpgMap, 'entries')).join('');
}

// ── Fuel form helpers ─────────────────────────────────────────────────────────

/** Show/hide the fuel extra fields based on the selected category. */
function onCategoryChange() {
  const cat = document.getElementById('cat')?.value;
  const ff  = document.getElementById('fuel-fields');
  if (!ff) return;
  if (cat === 'Fuel') ff.classList.add('visible');
  else                ff.classList.remove('visible');
  updatePplDisplay();
}

/** Auto-calculate and show price-per-litre as the user types amount/litres. */
function updatePplDisplay() {
  const amount = parseFloat(document.getElementById('amount')?.value) || 0;
  const litres = parseFloat(document.getElementById('litres')?.value) || 0;
  const ppl    = document.getElementById('ppl-display');
  if (ppl) ppl.value = (amount > 0 && litres > 0) ? (amount / litres).toFixed(3) : '';
}

// Wire up live p/litre recalculation
document.getElementById('amount').addEventListener('input', updatePplDisplay);
document.getElementById('litres').addEventListener('input', updatePplDisplay);

function toggleFullTank() {
  _isFullTank = !_isFullTank;
  const btn = document.getElementById('tank-toggle');
  btn.classList.toggle('active', _isFullTank);
  btn.innerHTML = `<span class="tank-icon">⛽</span> ${_isFullTank ? '✓ Full tank' : 'Full tank'}`;
}

function onEditCategoryChange() {
  const cat = document.getElementById('edit-cat').value;
  document.getElementById('edit-fuel-fields').style.display =
    cat === 'Fuel' ? 'block' : 'none';
}

function toggleEditFullTank() {
  _editIsFullTank = !_editIsFullTank;
  const btn = document.getElementById('edit-tank-toggle');
  btn.classList.toggle('active', _editIsFullTank);
  btn.innerHTML = `<span class="tank-icon">⛽</span> ${_editIsFullTank ? '✓ Full tank' : 'Full tank'}`;
}

// ── Add entry ─────────────────────────────────────────────────────────────────

async function addEntry() {
  if (!activeVehicleId) { showToast('Select a vehicle first'); return; }

  const amount = document.getElementById('amount').value;
  const cat    = document.getElementById('cat').value;
  const date   = document.getElementById('date').value;
  const note   = document.getElementById('note').value;

  if (!amount || parseFloat(amount) <= 0) { showToast('Enter a valid amount'); return; }
  if (!date)                               { showToast('Select a date');        return; }

  const body = {
    vehicle_id: activeVehicleId,
    category:   cat,
    amount:     parseFloat(amount),
    date,
    note,
  };

  if (cat === 'Fuel') {
    const litres   = document.getElementById('litres').value;
    const odometer = document.getElementById('odometer').value;
    if (litres)   body.litres   = parseFloat(litres);
    if (odometer) body.odometer = parseFloat(odometer);
    body.is_full_tank = _isFullTank;
  }

  const res = await fetch('/api/costs', {
    method:  'POST',
    headers: { 'Content-Type': 'application/json' },
    body:    JSON.stringify(body),
  });

  if (!res.ok) {
    const e = await res.json().catch(() => {});
    showToast(`Error: ${e?.error || 'Unknown'}`);
    return;
  }

  const data = await res.json();
  if (data.odometer_warning) showToastWarn(data.odometer_warning);

  // Remember category for rapid sequential entry
  _lastCategory = cat;

  // Reset fields — keep category and date for rapid entry
  document.getElementById('amount').value        = '';
  document.getElementById('note').value          = '';
  document.getElementById('litres').value        = '';
  document.getElementById('odometer').value      = '';
  document.getElementById('ppl-display').value   = '';
  if (_isFullTank) toggleFullTank();

  _mpgMapCache = null;
  await loadCosts();
  renderAll();
  loadOdometer();
  showToast('Entry added', 'success-toast');
}

// ── Delete entry ──────────────────────────────────────────────────────────────

async function deleteEntry(id) {
  if (!confirm('Delete this entry?')) return;
  await fetch(`/api/costs/${id}`, { method: 'DELETE' });
  costs       = costs.filter(c => c.id !== id);
  _mpgMapCache = null;
  renderAll();
  loadOdometer();
  showToast('Entry deleted');
}

// ── Edit modal ────────────────────────────────────────────────────────────────

function openEditModal(id) {
  const record = costs.find(c => c.id === id);
  if (!record) return;
  _editingId      = id;
  _editIsFullTank = record.is_full_tank || false;

  renderCategoryDropdowns();
  document.getElementById('edit-cat').value    = record.category;
  document.getElementById('edit-amount').value = record.amount;
  document.getElementById('edit-date').value   = record.date;
  document.getElementById('edit-note').value   = record.note || '';

  const ff = document.getElementById('edit-fuel-fields');
  if (record.category === 'Fuel') {
    ff.style.display = 'block';
    document.getElementById('edit-litres').value   = record.litres   || '';
    document.getElementById('edit-odometer').value = record.odometer || '';
    const btn = document.getElementById('edit-tank-toggle');
    btn.classList.toggle('active', _editIsFullTank);
    btn.innerHTML = `<span class="tank-icon">⛽</span> ${_editIsFullTank ? '✓ Full tank' : 'Full tank'}`;
  } else {
    ff.style.display = 'none';
  }

  document.getElementById('edit-modal').classList.add('open');
}

function closeEditModal() {
  _editingId = null;
  document.getElementById('edit-modal').classList.remove('open');
}

async function saveEdit() {
  if (!_editingId) return;
  const cat  = document.getElementById('edit-cat').value;
  const body = {
    category: cat,
    amount:   parseFloat(document.getElementById('edit-amount').value),
    date:     document.getElementById('edit-date').value,
    note:     document.getElementById('edit-note').value,
  };

  if (cat === 'Fuel') {
    const l = document.getElementById('edit-litres').value;
    const o = document.getElementById('edit-odometer').value;
    body.litres       = l ? parseFloat(l) : null;
    body.odometer     = o ? parseFloat(o) : null;
    body.is_full_tank = _editIsFullTank;
  }

  const res = await fetch(`/api/costs/${_editingId}`, {
    method:  'PUT',
    headers: { 'Content-Type': 'application/json' },
    body:    JSON.stringify(body),
  });

  if (!res.ok) {
    const e = await res.json().catch(() => {});
    showToast(`Error: ${e?.error || 'Unknown'}`);
    return;
  }

  closeEditModal();
  _mpgMapCache = null;
  await loadCosts();
  renderAll();
  loadOdometer();
  showToast('Entry updated', 'success-toast');
}

// ══════════════════════════════════════════════════════════════════════════════
// REPORTS
// ══════════════════════════════════════════════════════════════════════════════

/**
 * Destroy and re-create a Chart.js chart instance.
 * Also reveals the canvas and hides any loading/empty overlays.
 */
function makeChart(id, config) {
  if (_charts[id]) { _charts[id].destroy(); delete _charts[id]; }
  const canvas = document.getElementById(id);
  if (!canvas) return;
  canvas.style.display = '';
  const wrap = canvas.closest('.chart-wrap');
  if (wrap) {
    const spinner = wrap.querySelector('.chart-loading');
    const empty   = wrap.querySelector('.report-empty');
    if (spinner) spinner.style.display = 'none';
    if (empty)   empty.style.display   = 'none';
  }
  _charts[id] = new Chart(canvas, config);
}

/**
 * Read CSS custom property colours for the current theme.
 * Chart.js cannot use CSS variables directly, so we resolve them here.
 */
function chartColours() {
  const s = getComputedStyle(document.documentElement);
  const g = v => s.getPropertyValue(v).trim();
  return {
    text:    g('--text'),
    muted:   g('--muted'),
    border:  g('--border'),
    surface: g('--surface2'),
    accent:  g('--accent'),
    success: g('--success'),
    warning: g('--warning'),
    cats:    CAT_COLOURS.map(c => g(`--${c}`)),
  };
}

/** Common Chart.js options shared across all charts. */
function baseOptions(c) {
  return {
    responsive:          true,
    maintainAspectRatio: false,
    plugins: {
      legend: { labels: { color: c.muted, font: { family: 'Inter', size: 11 }, boxWidth: 12 } },
      tooltip: {
        backgroundColor: c.surface,
        titleColor:      c.text,
        bodyColor:       c.muted,
        borderColor:     c.border,
        borderWidth:     1,
      },
    },
    scales: {
      x: { ticks: { color: c.muted, font: { family: 'Inter', size: 11 } }, grid: { color: c.border } },
      y: { ticks: { color: c.muted, font: { family: 'Inter', size: 11 } }, grid: { color: c.border } },
    },
  };
}

function setReportPeriod(months) {
  _reportPeriod = months;
  document.querySelectorAll('.report-period-btn').forEach(b => b.classList.remove('active'));
  document.getElementById(`rp-${months}`).classList.add('active');
  loadReports();
}

/**
 * Show a loading spinner overlay on a chart canvas.
 * Does NOT destroy the canvas — makeChart() needs it to persist.
 */
function showChartLoading(id) {
  if (_charts[id]) { _charts[id].destroy(); delete _charts[id]; }
  const canvas = document.getElementById(id);
  if (!canvas) return;
  canvas.style.display = 'none';
  const wrap = canvas.closest('.chart-wrap');
  if (!wrap) return;
  let spinner = wrap.querySelector('.chart-loading');
  if (!spinner) {
    spinner = document.createElement('div');
    spinner.className = 'chart-loading';
    spinner.innerHTML = '<div class="chart-spinner"></div>Loading…';
    wrap.appendChild(spinner);
  }
  spinner.style.display = 'flex';
}

/**
 * Show an empty-state message on a chart canvas area.
 * Used when there's not enough data to draw the chart.
 */
function showChartEmpty(id, msg = 'Not enough data yet') {
  if (_charts[id]) { _charts[id].destroy(); delete _charts[id]; }
  const canvas = document.getElementById(id);
  if (!canvas) return;
  canvas.style.display = 'none';
  const wrap = canvas.closest('.chart-wrap');
  if (!wrap) return;
  const spinner = wrap.querySelector('.chart-loading');
  if (spinner) spinner.style.display = 'none';
  let empty = wrap.querySelector('.report-empty');
  if (!empty) {
    empty = document.createElement('div');
    empty.className = 'report-empty';
    wrap.appendChild(empty);
  }
  empty.innerHTML   = `<span class="report-empty-icon">📊</span>${msg}`;
  empty.style.display = 'flex';
}

async function loadReports() {
  if (!activeVehicleId) return;
  const p   = _reportPeriod;
  const vid = activeVehicleId;
  const sym = settings.currency_symbol;

  // Show spinners immediately while all fetches run in parallel
  ['chart-monthly','chart-category','chart-cumulative',
   'chart-mpg','chart-kpl','chart-ppl',
   'chart-cpm','chart-interval','chart-fuelvsother'].forEach(showChartLoading);

  const colours = chartColours();

  const [summary, monthly, category, efficiency, cumulative,
         cpm, interval, fuelvsother, annual] = await Promise.all([
    fetch(`/api/reports/summary?vehicle_id=${vid}&months=${p}`).then(r=>r.json()).catch(()=>({})),
    fetch(`/api/reports/monthly?vehicle_id=${vid}&months=${p}`).then(r=>r.json()).catch(()=>({})),
    fetch(`/api/reports/category?vehicle_id=${vid}&months=${p}`).then(r=>r.json()).catch(()=>({})),
    fetch(`/api/reports/efficiency?vehicle_id=${vid}&months=${p}`).then(r=>r.json()).catch(()=>[]),
    fetch(`/api/reports/cumulative?vehicle_id=${vid}&months=${p}`).then(r=>r.json()).catch(()=>[]),
    fetch(`/api/reports/costpermile?vehicle_id=${vid}&months=${p}`).then(r=>r.json()).catch(()=>({})),
    fetch(`/api/reports/fillinterval?vehicle_id=${vid}&months=${p}`).then(r=>r.json()).catch(()=>({})),
    fetch(`/api/reports/fuelvsother?vehicle_id=${vid}&months=${p}`).then(r=>r.json()).catch(()=>({})),
    fetch(`/api/reports/annual?vehicle_id=${vid}`).then(r=>r.json()).catch(()=>({})),
  ]);

  // ── KPI strip ──────────────────────────────────────────────────────────────
  const kpis = document.getElementById('report-kpis');
  if (kpis) {
    const fc = v => v != null ? `${sym}${parseFloat(v).toFixed(2)}` : '—';
    const fn = (v, u = '') => v != null ? `${parseFloat(v).toFixed(1)}${u}` : '—';
    const fd = (v, u = '') => v != null ? `${parseFloat(v).toFixed(2)}${u}` : '—';
    kpis.innerHTML = [
      { label: 'Total Spend',  value: fc(summary.total_spend),       cls: 'accent'  },
      { label: 'Avg / Month',  value: fc(summary.avg_monthly),       cls: ''        },
      { label: 'Total Litres', value: fn(summary.total_litres, 'L'), cls: ''        },
      { label: 'Avg p/Litre',  value: summary.avg_ppl != null
          ? `${parseFloat(summary.avg_ppl).toFixed(3)}p` : '—',      cls: ''        },
      { label: 'Avg MPG',      value: fn(summary.avg_mpg,  ' mpg'), cls: 'success' },
      { label: 'Best MPG',     value: fn(summary.best_mpg, ' mpg'), cls: 'success' },
      { label: 'Avg km/L',     value: fd(summary.avg_kpl,  ' km/L'),cls: 'success' },
      { label: 'Best km/L',    value: fd(summary.best_kpl, ' km/L'),cls: 'success' },
    ].map(k => `
      <div class="report-stat">
        <div class="report-stat-label">${k.label}</div>
        <div class="report-stat-value ${k.cls}">${k.value}</div>
      </div>`).join('');
  }

  // ── Monthly stacked bar ────────────────────────────────────────────────────
  if (!monthly.months || monthly.months.length === 0) {
    showChartEmpty('chart-monthly', 'No entries in this period');
  } else {
    const c = colours;
    makeChart('chart-monthly', {
      type: 'bar',
      data: {
        labels:   monthly.months,
        datasets: (monthly.categories || []).map((cat, i) => ({
          label:           cat,
          data:            monthly.series[cat],
          backgroundColor: c.cats[i % c.cats.length] + 'cc',
          borderColor:     c.cats[i % c.cats.length],
          borderWidth:     1,
          borderRadius:    3,
        })),
      },
      options: {
        ...baseOptions(c),
        plugins: {
          ...baseOptions(c).plugins,
          tooltip: { ...baseOptions(c).plugins.tooltip, mode: 'index', intersect: false },
        },
        scales: {
          ...baseOptions(c).scales,
          x: { ...baseOptions(c).scales.x, stacked: true },
          y: { ...baseOptions(c).scales.y, stacked: true,
               ticks: { ...baseOptions(c).scales.y.ticks, callback: v => `${sym}${v}` } },
        },
      },
    });
  }

  // ── Category doughnut ─────────────────────────────────────────────────────
  if (!category.categories || category.categories.length === 0) {
    showChartEmpty('chart-category');
  } else {
    const c = colours;
    makeChart('chart-category', {
      type: 'doughnut',
      data: {
        labels:   category.categories,
        datasets: [{
          data:            category.totals,
          backgroundColor: c.cats.slice(0, category.categories.length),
          borderColor:     c.border,
          borderWidth:     2,
        }],
      },
      options: {
        responsive: true, maintainAspectRatio: false, cutout: '60%',
        plugins: {
          legend:  { position: 'bottom',
                     labels: { color: c.muted, font: { family: 'Inter', size: 11 }, boxWidth: 12 } },
          tooltip: { ...baseOptions(c).plugins.tooltip,
                     callbacks: { label: ctx => `${sym}${ctx.parsed.toFixed(2)}` } },
        },
      },
    });
  }

  // ── Cumulative spend ──────────────────────────────────────────────────────
  if (!cumulative || cumulative.length < 2) {
    showChartEmpty('chart-cumulative');
  } else {
    const c = colours;
    makeChart('chart-cumulative', {
      type: 'line',
      data: {
        labels:   cumulative.map(p => fmtDate(p.date)),
        datasets: [{ label: 'Cumulative Spend', data: cumulative.map(p => p.total),
          borderColor: c.accent, backgroundColor: c.accent + '22',
          fill: true, tension: 0.3, pointRadius: 2, borderWidth: 2 }],
      },
      options: { ...baseOptions(c), scales: { ...baseOptions(c).scales,
        y: { ...baseOptions(c).scales.y, ticks: {
          ...baseOptions(c).scales.y.ticks, callback: v => `${sym}${v}` } } } },
    });
  }

  // ── MPG trend ─────────────────────────────────────────────────────────────
  const mpgPts = efficiency.filter(e => e.mpg != null);
  if (mpgPts.length < 2) {
    showChartEmpty('chart-mpg', 'Need 2+ consecutive full-tank fills to calculate MPG');
  } else {
    const c = colours;
    makeChart('chart-mpg', {
      type: 'line',
      data: { labels: mpgPts.map(e => fmtDate(e.date)),
              datasets: [{ label: 'MPG', data: mpgPts.map(e => e.mpg),
                borderColor: c.success, backgroundColor: c.success + '22',
                fill: true, tension: 0.3, pointRadius: 3, borderWidth: 2 }] },
      options: { ...baseOptions(c), scales: { ...baseOptions(c).scales,
        y: { ...baseOptions(c).scales.y, ticks: {
          ...baseOptions(c).scales.y.ticks, callback: v => `${v} mpg` } } } },
    });
  }

  // ── km/L trend ────────────────────────────────────────────────────────────
  const kplPts = efficiency.filter(e => e.kpl != null);
  if (kplPts.length < 2) {
    showChartEmpty('chart-kpl', 'Need 2+ consecutive full-tank fills to calculate km/L');
  } else {
    const c = colours;
    makeChart('chart-kpl', {
      type: 'line',
      data: { labels: kplPts.map(e => fmtDate(e.date)),
              datasets: [{ label: 'km/L', data: kplPts.map(e => e.kpl),
                borderColor: c.accent, backgroundColor: c.accent + '22',
                fill: true, tension: 0.3, pointRadius: 3, borderWidth: 2 }] },
      options: { ...baseOptions(c), scales: { ...baseOptions(c).scales,
        y: { ...baseOptions(c).scales.y, ticks: {
          ...baseOptions(c).scales.y.ticks, callback: v => `${v} km/L` } } } },
    });
  }

  // ── Price per litre ───────────────────────────────────────────────────────
  const pplPts = efficiency.filter(e => e.ppl != null);
  if (pplPts.length < 2) {
    showChartEmpty('chart-ppl', 'Record fuel with litres to see price trend');
  } else {
    const c = colours;
    makeChart('chart-ppl', {
      type: 'line',
      data: { labels: pplPts.map(e => fmtDate(e.date)),
              datasets: [{ label: 'p/Litre', data: pplPts.map(e => e.ppl),
                borderColor: c.warning, backgroundColor: c.warning + '22',
                fill: true, tension: 0.3, pointRadius: 3, borderWidth: 2 }] },
      options: { ...baseOptions(c), scales: { ...baseOptions(c).scales,
        y: { ...baseOptions(c).scales.y, ticks: {
          ...baseOptions(c).scales.y.ticks,
          callback: v => `${parseFloat(v).toFixed(3)}` } } } },
    });
  }

  // ── Cost per mile ─────────────────────────────────────────────────────────
  if (!cpm.months || cpm.months.length < 2) {
    showChartEmpty('chart-cpm', 'Need odometer readings on fuel entries to calculate cost per mile');
  } else {
    const c = colours;
    makeChart('chart-cpm', {
      type: 'bar',
      data: { labels: cpm.months,
              datasets: [{ label: 'Cost/mile', data: cpm.cpm,
                backgroundColor: c.cats[4] + 'cc', borderColor: c.cats[4],
                borderWidth: 1, borderRadius: 3 }] },
      options: { ...baseOptions(c), scales: { ...baseOptions(c).scales,
        y: { ...baseOptions(c).scales.y, ticks: {
          ...baseOptions(c).scales.y.ticks,
          callback: v => `${sym}${parseFloat(v).toFixed(3)}` } } } },
    });
  }

  // ── Fill-up interval ──────────────────────────────────────────────────────
  if (!interval.dates || interval.dates.length < 2) {
    showChartEmpty('chart-interval', 'Need more fuel entries to show fill-up intervals');
  } else {
    const c = colours;
    makeChart('chart-interval', {
      type: 'line',
      data: { labels: interval.dates.map(d => fmtDate(d)),
              datasets: [{ label: 'Days between fills', data: interval.days,
                borderColor: c.cats[1], backgroundColor: c.cats[1] + '22',
                fill: true, tension: 0.2, pointRadius: 3, borderWidth: 2 }] },
      options: { ...baseOptions(c), scales: { ...baseOptions(c).scales,
        y: { ...baseOptions(c).scales.y, ticks: {
          ...baseOptions(c).scales.y.ticks, callback: v => `${v} days` } } } },
    });
  }

  // ── Fuel vs other costs ───────────────────────────────────────────────────
  if (!fuelvsother.months || fuelvsother.months.length === 0) {
    showChartEmpty('chart-fuelvsother', 'No data for this period');
  } else {
    const c = colours;
    makeChart('chart-fuelvsother', {
      type: 'line',
      data: {
        labels:   fuelvsother.months,
        datasets: [
          { label: 'Fuel',  data: fuelvsother.fuel,
            borderColor: c.cats[0], backgroundColor: c.cats[0] + '55',
            fill: true, tension: 0.3, pointRadius: 2, borderWidth: 2 },
          { label: 'Other', data: fuelvsother.other,
            borderColor: c.cats[1], backgroundColor: c.cats[1] + '55',
            fill: true, tension: 0.3, pointRadius: 2, borderWidth: 2 },
        ],
      },
      options: {
        ...baseOptions(c),
        plugins: { ...baseOptions(c).plugins,
          tooltip: { ...baseOptions(c).plugins.tooltip, mode: 'index', intersect: false } },
        scales: { ...baseOptions(c).scales,
          y: { ...baseOptions(c).scales.y,
               ticks: { ...baseOptions(c).scales.y.ticks, callback: v => `${sym}${v}` } } },
      },
    });
  }

  // ── Annual breakdown table ────────────────────────────────────────────────
  renderAnnualTable(annual, sym);
}

/**
 * Render the year-by-year breakdown table on the Reports page.
 * Most recent year shown first.
 */
function renderAnnualTable(annual, sym) {
  const wrap = document.getElementById('annual-table-wrap');
  if (!wrap) return;

  if (!annual.rows || annual.rows.length === 0) {
    wrap.innerHTML = `
      <div class="report-empty" style="height:80px">
        <span class="report-empty-icon">📋</span>No annual data yet
      </div>`;
    return;
  }

  const cats       = annual.categories || [];
  const catHeaders = cats.map(cat => `<th>${cat}</th>`).join('');
  const rows       = [...annual.rows].reverse().map(row => {
    const catCells = cats.map(cat => {
      const val = row.categories[cat] || 0;
      return `<td>${val > 0 ? `${sym}${val.toFixed(2)}` : '—'}</td>`;
    }).join('');
    return `
      <tr>
        <td>${row.year}</td>
        <td class="total-col">${sym}${row.total.toFixed(2)}</td>
        ${catCells}
        <td class="mpg-col">${row.avg_mpg ? `${row.avg_mpg} mpg` : '—'}</td>
        <td>${row.miles ? `${row.miles.toLocaleString()} mi` : '—'}</td>
      </tr>`;
  }).join('');

  wrap.innerHTML = `
    <table class="annual-table">
      <thead>
        <tr>
          <th style="text-align:left">Year</th>
          <th>Total</th>
          ${catHeaders}
          <th>Avg MPG</th>
          <th>Miles</th>
        </tr>
      </thead>
      <tbody>${rows}</tbody>
    </table>`;
}

// ══════════════════════════════════════════════════════════════════════════════
// VEHICLES PAGE
// ══════════════════════════════════════════════════════════════════════════════

function renderVehicleGrid() {
  const grid   = document.getElementById('vehicle-grid');
  const prompt = document.getElementById('first-run-prompt');
  if (!grid) return;
  if (vehicles.length === 0) {
    grid.innerHTML = '';
    if (prompt) prompt.style.display = 'block';
    return;
  }
  if (prompt) prompt.style.display = 'none';
  _renderVehicleGridWithTotals();
}

/** Fetch all-vehicle costs to show per-vehicle totals on the vehicle cards. */
async function _renderVehicleGridWithTotals() {
  let allCosts = [];
  try {
    const r = await fetch('/api/costs');
    if (r.ok) allCosts = await r.json();
  } catch (e) { /* show £0 if fetch fails */ }

  const sym  = settings.currency_symbol;
  const grid = document.getElementById('vehicle-grid');

  grid.innerHTML = vehicles.map(v => {
    const tot      = allCosts
      .filter(c => c.vehicle_id === v.id)
      .reduce((s, c) => s + parseFloat(c.amount || 0), 0);
    const isActive = v.id === activeVehicleId;

    return `
      <div class="vehicle-card ${isActive ? 'active-vehicle' : ''}">
        <span class="vc-active-badge">Active</span>
        <div class="vc-header">
          <div class="vc-avatar">${v.name[0].toUpperCase()}</div>
          <div>
            <div class="vc-name">${v.name}</div>
            <div class="vc-reg">${v.registration || 'No reg'}</div>
          </div>
        </div>
        <div class="vc-details">
          ${[
            { label: 'Make',   value: v.make   || '—' },
            { label: 'Model',  value: v.model  || '—' },
            { label: 'Year',   value: v.year   || '—' },
            { label: 'Colour', value: v.colour || '—' },
          ].map(d => `
            <div class="vc-detail">
              <span class="vc-detail-label">${d.label}</span>
              <span class="vc-detail-value">${d.value}</span>
            </div>`).join('')}
        </div>
        ${v.notes
          ? `<div style="font-size:0.75rem;color:var(--muted);margin-bottom:0.75rem;font-style:italic">${v.notes}</div>`
          : ''}
        <div class="vc-cost-strip">
          <span class="vc-cost-label">Total costs recorded</span>
          <span class="vc-cost-amount">${sym}${tot.toFixed(2)}</span>
        </div>
        <div class="vc-actions">
          ${!isActive
            ? `<button class="btn btn-ghost btn-sm"
                       onclick="selectVehicle('${v.id}');showPage('dashboard')">Set active</button>`
            : ''}
          <button class="btn btn-ghost btn-sm" onclick="startVehicleEdit('${v.id}')">Edit</button>
          <button class="btn btn-danger-ghost btn-sm" onclick="promptDeleteVehicle('${v.id}')">Delete</button>
        </div>
      </div>`;
  }).join('');
}

function startVehicleEdit(id) {
  const v = vehicles.find(v => v.id === id);
  if (!v) return;
  _editingVehicleId = id;
  document.getElementById('vf-name').value   = v.name;
  document.getElementById('vf-make').value   = v.make         || '';
  document.getElementById('vf-model').value  = v.model        || '';
  document.getElementById('vf-year').value   = v.year         || '';
  document.getElementById('vf-colour').value = v.colour       || '';
  document.getElementById('vf-reg').value    = v.registration || '';
  document.getElementById('vf-notes').value  = v.notes        || '';
  document.getElementById('vehicle-form-title').textContent = 'Edit Vehicle';
  document.getElementById('vf-submit-btn').textContent      = 'Save Changes';
  document.getElementById('vf-cancel-btn').style.display    = 'inline-flex';
  document.getElementById('vehicle-form-panel').scrollIntoView({ behavior: 'smooth' });
}

function cancelVehicleEdit() {
  _editingVehicleId = null;
  ['vf-name','vf-make','vf-model','vf-year','vf-colour','vf-reg','vf-notes']
    .forEach(id => document.getElementById(id).value = '');
  document.getElementById('vehicle-form-title').textContent = 'Add New Vehicle';
  document.getElementById('vf-submit-btn').textContent      = 'Add Vehicle';
  document.getElementById('vf-cancel-btn').style.display    = 'none';
}

async function submitVehicleForm() {
  const name = document.getElementById('vf-name').value.trim();
  if (!name) { showToast('Vehicle name is required'); return; }

  const body = {
    name,
    make:         document.getElementById('vf-make').value.trim(),
    model:        document.getElementById('vf-model').value.trim(),
    year:         document.getElementById('vf-year').value || null,
    colour:       document.getElementById('vf-colour').value.trim(),
    registration: document.getElementById('vf-reg').value.trim(),
    notes:        document.getElementById('vf-notes').value.trim(),
  };

  const url    = _editingVehicleId ? `/api/vehicles/${_editingVehicleId}` : '/api/vehicles';
  const method = _editingVehicleId ? 'PUT' : 'POST';
  const res    = await fetch(url, {
    method, headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body),
  });

  if (!res.ok) {
    const e = await res.json().catch(() => {});
    showToast(`Error: ${e?.error || 'Unknown'}`);
    return;
  }

  const saved = await res.json();
  if (_editingVehicleId) {
    const i = vehicles.findIndex(v => v.id === _editingVehicleId);
    if (i >= 0) vehicles[i] = saved;
    showToast('Vehicle updated', 'success-toast');
  } else {
    vehicles.push(saved);
    if (vehicles.length === 1) {
      activeVehicleId = saved.id;
      localStorage.setItem('autoledger-vehicle', saved.id);
      await loadCosts();
    }
    showToast('Vehicle added', 'success-toast');
  }

  cancelVehicleEdit();
  renderVehicleSwitcher();
  renderVehicleGrid();
  renderAll();
  updateSplash();
}

function promptDeleteVehicle(id) {
  const v = vehicles.find(v => v.id === id);
  if (!v) return;
  _deletingVehicleId = id;
  document.getElementById('dv-name').textContent = v.name;
  document.getElementById('delete-vehicle-modal').classList.add('open');
}

function closeDeleteVehicleModal() {
  _deletingVehicleId = null;
  document.getElementById('delete-vehicle-modal').classList.remove('open');
}

async function confirmDeleteVehicle(cascade) {
  if (!_deletingVehicleId) return;
  const res  = await fetch(
    `/api/vehicles/${_deletingVehicleId}?cascade=${cascade}`, { method: 'DELETE' }
  );
  const data = await res.json();
  vehicles   = vehicles.filter(v => v.id !== _deletingVehicleId);

  if (_deletingVehicleId === activeVehicleId) {
    activeVehicleId = vehicles.length > 0 ? vehicles[0].id : null;
    if (activeVehicleId) localStorage.setItem('autoledger-vehicle', activeVehicleId);
    else                 localStorage.removeItem('autoledger-vehicle');
    _mpgMapCache = null;
    await loadCosts();
  }

  closeDeleteVehicleModal();
  renderVehicleSwitcher();
  renderVehicleGrid();
  renderAll();
  updateSplash();
  showToast(cascade
    ? `Vehicle deleted (${data.costs_deleted} costs removed)`
    : 'Vehicle deleted');
}

// ══════════════════════════════════════════════════════════════════════════════
// SETTINGS
// ══════════════════════════════════════════════════════════════════════════════

async function saveSettings() {
  try {
    const res = await fetch('/api/settings', {
      method:  'POST',
      headers: { 'Content-Type': 'application/json' },
      body:    JSON.stringify(settings),
    });
    if (!res.ok) throw new Error((await res.json()).error);

    // Use server response as source of truth — confirms what was written to disk
    settings       = await res.json();
    _settingsDirty = false;

    renderCategoryDropdowns();
    renderFilterPills();
    renderSummaryCards();
    renderSettingsUI();

    const msg = document.getElementById('settings-saved-msg');
    msg.textContent = `✓ Saved — ${settings.categories.length} categories`;
    msg.classList.add('show');
    setTimeout(() => msg.classList.remove('show'), 3000);
    showToast('Settings saved', 'success-toast');
  } catch (e) {
    showToast(`Error saving settings: ${e.message}`);
  }
}

function renderSettingsUI() { renderCurrencyChips(); renderCategoryList(); }

const COMMON_CURRENCIES = [
  { sym: '£', label: 'GBP' }, { sym: '$', label: 'USD' },
  { sym: '€', label: 'EUR' }, { sym: '¥', label: 'JPY' },
  { sym: 'A$',label: 'AUD' }, { sym: 'C$',label: 'CAD' },
  { sym: 'Fr', label: 'CHF' }, { sym: 'kr', label: 'NOK' },
  { sym: 'zł', label: 'PLN' }, { sym: '₹', label: 'INR' },
  { sym: 'R$', label: 'BRL' }, { sym: 'R',  label: 'ZAR' },
];

function renderCurrencyChips() {
  const grid = document.getElementById('currency-grid');
  if (!grid) return;
  grid.innerHTML = COMMON_CURRENCIES.map(c => `
    <button class="currency-chip ${settings.currency_symbol === c.sym ? 'active' : ''}"
            onclick="selectCurrencyChip('${c.sym}')">
      <span class="currency-sym">${c.sym}</span><span>${c.label}</span>
    </button>`).join('');
}

function selectCurrencyChip(sym) {
  settings.currency_symbol = sym;
  document.getElementById('custom-currency').value = '';
  renderCurrencyChips();
  _settingsDirty = true;
}

function setCustomCurrency() {
  const val = document.getElementById('custom-currency').value.trim();
  if (!val) { showToast('Enter a symbol first'); return; }
  settings.currency_symbol = val.slice(0, 4);
  renderCurrencyChips();
  _settingsDirty = true;
  showToast(`Currency set to "${settings.currency_symbol}" — click Save`);
}

function renderCategoryList() {
  const list = document.getElementById('category-list');
  if (!list) return;
  if (settings.categories.length === 0) {
    list.innerHTML = `
      <div class="empty-state" style="padding:1rem">
        <span class="empty-sub">No categories.</span>
      </div>`;
    return;
  }
  list.innerHTML = settings.categories.map((cat, i) => `
    <div class="category-row">
      <span class="cat-colour-dot" style="background:${catColourVar(cat)}"></span>
      <span>${cat}</span>
      <button class="btn btn-danger-ghost"
              onclick="removeCategory(${i})"
              ${settings.categories.length <= 1 ? 'disabled' : ''}>✕</button>
    </div>`).join('');
}

function addCategory() {
  const input = document.getElementById('new-cat-input');
  const name  = input.value.trim();
  if (!name) { showToast('Enter a category name'); return; }
  if (settings.categories.map(c => c.toLowerCase()).includes(name.toLowerCase())) {
    showToast('Already exists');
    return;
  }
  settings.categories.push(name);
  input.value    = '';
  _settingsDirty = true;
  renderCategoryList();
  showToast(`"${name}" added — click Save`);
}

function removeCategory(index) {
  if (settings.categories.length <= 1) {
    showToast('At least one category required');
    return;
  }
  const removed  = settings.categories.splice(index, 1)[0];
  _settingsDirty = true;
  renderCategoryList();
  showToast(`"${removed}" removed — click Save`);
}

// ══════════════════════════════════════════════════════════════════════════════
// IMPORT / EXPORT
// ══════════════════════════════════════════════════════════════════════════════

function exportJSON() {
  const a = document.createElement('a');
  a.href = '/api/export/json';
  a.download = '';
  a.click();
  showToast('Export downloaded');
}

async function importJSON(input) {
  const file = input.files[0];
  if (!file) return;
  const badge = document.getElementById('json-result');
  const fd    = new FormData();
  fd.append('file', file);
  try {
    const res  = await fetch('/api/import/json', { method: 'POST', body: fd });
    const data = await res.json();
    if (res.ok) {
      showResult(badge, `✓ ${data.imported} imported, ${data.skipped} skipped`, 'ok');
      _mpgMapCache = null;
      await loadVehicles();
      await loadCosts();
      renderVehicleSwitcher();
      renderAll();
      showToast(`Imported ${data.imported} records`, 'success-toast');
    } else {
      showResult(badge, `✗ ${data.error}`, 'err');
    }
  } catch (e) {
    showResult(badge, `✗ ${e.message}`, 'err');
  }
  input.value = '';
}

async function importLubeLogger(input) {
  if (!activeVehicleId) { showToast('Select a vehicle first'); return; }
  const file = input.files[0];
  if (!file) return;
  const badge = document.getElementById('lub-result');
  const fd    = new FormData();
  fd.append('file', file);
  fd.append('vehicle_id', activeVehicleId);
  try {
    const res  = await fetch('/api/import/lubelogger', { method: 'POST', body: fd });
    const data = await res.json();
    if (res.ok) {
      const errNote = data.errors.length ? ` (${data.errors.length} errors)` : '';
      showResult(badge, `✓ ${data.imported} ${data.detected_type} records imported${errNote}`, 'ok');
      _mpgMapCache = null;
      await loadCosts();
      renderAll();
      loadOdometer();
      showToast(`Imported ${data.imported} LubeLogger records`, 'success-toast');
    } else {
      showResult(badge, `✗ ${data.error}`, 'err');
    }
  } catch (e) {
    showResult(badge, `✗ ${e.message}`, 'err');
  }
  input.value = '';
}

async function reimportLubeLogger(input) {
  if (!activeVehicleId) { showToast('Select a vehicle first'); return; }
  const file = input.files[0];
  if (!file) return;
  const badge = document.getElementById('relub-result');

  if (!confirm(
    'This will delete all existing LubeLogger records for this vehicle and re-import. Continue?'
  )) { input.value = ''; return; }

  // Step 1: delete existing lubelogger records
  try {
    const del  = await fetch('/api/costs/bulk-delete', {
      method:  'POST',
      headers: { 'Content-Type': 'application/json' },
      body:    JSON.stringify({ vehicle_id: activeVehicleId, source: 'lubelogger' }),
    });
    const dd = await del.json();
    if (!del.ok) { showResult(badge, `✗ Delete failed: ${dd.error}`, 'err'); input.value = ''; return; }
    showResult(badge, `Deleted ${dd.deleted} old records, re-importing…`, 'ok');
  } catch (e) {
    showResult(badge, `✗ ${e.message}`, 'err');
    input.value = '';
    return;
  }

  // Step 2: re-import from CSV
  const fd = new FormData();
  fd.append('file', file);
  fd.append('vehicle_id', activeVehicleId);
  try {
    const res  = await fetch('/api/import/lubelogger', { method: 'POST', body: fd });
    const data = await res.json();
    if (res.ok) {
      showResult(badge, `✓ ${data.imported} ${data.detected_type} records re-imported`, 'ok');
      _mpgMapCache = null;
      await loadCosts();
      renderAll();
      loadOdometer();
      showToast(`Re-imported ${data.imported} records`, 'success-toast');
    } else {
      showResult(badge, `✗ ${data.error}`, 'err');
    }
  } catch (e) {
    showResult(badge, `✗ ${e.message}`, 'err');
  }
  input.value = '';
}

// ── Utilities ─────────────────────────────────────────────────────────────────

function showResult(el, msg, type) {
  el.textContent = msg;
  el.className   = `io-result ${type}`;
}

/**
 * Show a toast notification.
 * @param {string} msg  - message text
 * @param {string} cls  - optional extra CSS class (e.g. 'success-toast', 'warn')
 */
function showToast(msg, cls = '') {
  const t     = document.getElementById('toast');
  t.textContent = msg;
  t.className   = `toast show ${cls}`.trim();
  setTimeout(() => t.classList.remove('show'), 2600);
}

function showToastWarn(msg) { showToast(msg, 'warn'); }

// ── Initialisation ────────────────────────────────────────────────────────────

// Close modals when clicking the overlay background
['edit-modal', 'delete-vehicle-modal'].forEach(id => {
  document.getElementById(id).addEventListener('click', function (e) {
    if (e.target === this) {
      if (id === 'edit-modal') closeEditModal();
      else closeDeleteVehicleModal();
    }
  });
});

// Close vehicle dropdown when clicking anywhere outside the switcher widget
document.addEventListener('click', e => {
  if (!e.target.closest('.vehicle-switcher') && _dropdownOpen) {
    closeVehicleDropdown();
  }
});

// Set today's date as default in the add form
document.getElementById('date').value = new Date().toISOString().split('T')[0];

initTheme();
init();
