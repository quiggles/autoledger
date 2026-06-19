"""
routes/reports.py
-----------------
Blueprint providing pre-aggregated data for the Reports page.

Endpoints:
  GET /api/reports/summary?vehicle_id=&months=
  GET /api/reports/monthly?vehicle_id=&months=
  GET /api/reports/category?vehicle_id=&months=
  GET /api/reports/efficiency?vehicle_id=&months=
  GET /api/reports/cumulative?vehicle_id=&months=
  ... plus costpermile / fillinterval / fuelvsother / annual

Robustness (v2.0.0)
-------------------
Every aggregation reads ``amount`` / ``litres`` / ``odometer`` through the
defensive ``_amount`` / ``_num`` helpers. Previously a single malformed record
(e.g. ``amount: "n/a"`` from a bad import) raised inside an unguarded
``float(c["amount"])`` and 500'd the **entire** report. Now a bad value is
skipped and logged, so one rogue row can no longer take down a whole page.

Changelog:
  v1.5.0  Initial — all five endpoints
  v1.5.3  Fixed date sorting bug (DD/MM/YYYY was sorting as string)
  v1.6.0  Efficiency returns record IDs for reliable frontend matching;
           efficiency respects months period filter;
           MPG sanity bounds widened to 10-100 to handle diverse vehicles;
           parse_date_to_iso shared with filter for consistent date handling
  v2.0.0  Defensive numeric coercion across all aggregations (skip + log bad
           records instead of 500ing); MPG sanity bounds now read from settings
           (mpg_min / mpg_max) instead of hardcoded constants.
"""

import logging
from collections import defaultdict
from datetime import date, datetime

from dateutil.relativedelta import relativedelta
from flask import Blueprint, jsonify, request

from .data import load_data, parse_date_to_iso
from .logging_config import log_event
from .settings import load_settings

reports_bp = Blueprint("reports", __name__)

LITRES_PER_GALLON = 4.54609

# Fallback MPG sanity bounds used only if settings somehow lack them. The live
# values come from settings (mpg_min / mpg_max) via _mpg_bounds().
DEFAULT_MPG_MIN = 10
DEFAULT_MPG_MAX = 100


# ── Defensive numeric coercion ────────────────────────────────────────────────

def _amount(record: dict) -> float | None:
    """
    Return a record's ``amount`` as a float, or ``None`` if it is missing or
    malformed. A malformed value is logged (not swallowed silently) and skipped
    by the caller, so one bad record cannot crash an entire aggregation.
    """
    raw = record.get("amount")
    try:
        return float(raw)
    except (TypeError, ValueError):
        log_event(
            "bad_amount_skipped",
            level=logging.WARNING,
            id=record.get("id"),
            value=raw,
        )
        return None


def _num(record: dict, field: str) -> float | None:
    """
    Return ``record[field]`` as a float, or ``None`` if missing/malformed.
    Used for ``litres`` and ``odometer``. Logs malformed values for visibility.
    """
    raw = record.get(field)
    if raw is None or raw == "":
        return None
    try:
        return float(raw)
    except (TypeError, ValueError):
        log_event(
            "bad_number_skipped",
            level=logging.WARNING,
            id=record.get("id"),
            field=field,
            value=raw,
        )
        return None


def _mpg_bounds() -> tuple[float, float]:
    """
    Read the configurable MPG sanity bounds from settings, falling back to the
    historical 10–100 defaults if they are absent or invalid.
    """
    s = load_settings()
    try:
        lo = float(s.get("mpg_min", DEFAULT_MPG_MIN))
        hi = float(s.get("mpg_max", DEFAULT_MPG_MAX))
        if lo < hi:
            return lo, hi
    except (TypeError, ValueError):
        pass
    return DEFAULT_MPG_MIN, DEFAULT_MPG_MAX


# ── Date helpers ──────────────────────────────────────────────────────────────

def _cutoff(months: int) -> str:
    """Return ISO date string `months` ago from today."""
    return (date.today() - relativedelta(months=months)).strftime("%Y-%m-%d")


def _filter(vehicle_id: str, months: int | None) -> list:
    """Load and filter costs by vehicle and optional date cutoff."""
    data = [c for c in load_data() if c.get("vehicle_id") == vehicle_id]
    if months:
        cut = _cutoff(months)
        data = [c for c in data if parse_date_to_iso(c.get("date", "")) >= cut]
    return data


# ── Efficiency helpers ────────────────────────────────────────────────────────

def _mpg(litres: float, miles: float) -> float | None:
    """Calculate MPG (UK imperial) from litres used over miles driven."""
    if not litres or not miles or miles <= 0:
        return None
    return round((miles / (litres / LITRES_PER_GALLON)), 2)


def _kpl(mpg: float) -> float:
    """Convert UK MPG to km per litre."""
    return round(mpg * 1.60934 / LITRES_PER_GALLON, 2)


def _compute_efficiency(vehicle_costs: list, cutoff_date: str | None = None) -> list:
    """
    Calculate MPG and km/L for each consecutive pair of full-tank fill-ups.

    Always uses the FULL history to find consecutive fill pairs (so MPG
    is always calculated from the correct previous fill), then filters
    results to cutoff_date for display.

    Numeric fields are coerced defensively — a fill whose litres/odometer/amount
    cannot be parsed is excluded rather than raising.

    Returns records with:
      id, date, mpg, kpl, ppl, litres, odometer, miles, amount
    """
    mpg_min, mpg_max = _mpg_bounds()

    # Build the candidate list defensively: a fill must be Fuel, flagged
    # full-tank, and have parseable positive litres + odometer. Bad numeric
    # values are dropped here (via _num) rather than crashing the comprehension.
    fills = []
    for c in vehicle_costs:
        if c.get("category") != "Fuel" or not c.get("is_full_tank"):
            continue
        litres = _num(c, "litres")
        odo = _num(c, "odometer")
        if not litres or litres <= 0 or not odo or odo <= 0:
            continue
        # Cache the parsed values so we do not re-coerce below.
        c = {**c, "_litres": litres, "_odo": odo}
        fills.append(c)

    # Normalise dates and sort chronologically
    for f in fills:
        f["_iso"] = parse_date_to_iso(f.get("date", ""))
    fills.sort(key=lambda c: c["_iso"])

    results = []
    for i, fill in enumerate(fills):
        litres = fill["_litres"]
        odo    = fill["_odo"]
        amount = _amount(fill) or 0.0
        ppl    = round(amount / litres, 3) if litres else None
        mpg    = None
        kpl    = None
        miles  = None

        if i > 0:
            prev_odo = fills[i - 1]["_odo"]
            miles    = round(odo - prev_odo, 1)
            if miles > 0:
                raw_mpg = _mpg(litres, miles)
                if raw_mpg and mpg_min <= raw_mpg <= mpg_max:
                    mpg = raw_mpg
                    kpl = _kpl(mpg)

        results.append({
            "id":       fill.get("id"),   # included so frontend can match by ID
            "date":     fill["_iso"],
            "mpg":      mpg,
            "kpl":      kpl,
            "ppl":      ppl,
            "litres":   litres,
            "odometer": odo,
            "amount":   amount,
            "miles":    miles,
        })

    # Apply date filter AFTER computing so consecutive-fill pairs are correct
    if cutoff_date:
        results = [r for r in results if r["date"] >= cutoff_date]

    return results


# ── GET /api/reports/summary ──────────────────────────────────────────────────

@reports_bp.route("/reports/summary", methods=["GET"])
def report_summary():
    """Top-level KPI metrics for the active vehicle and time window."""
    vehicle_id = request.args.get("vehicle_id", "")
    months     = int(request.args.get("months", 0))
    if not vehicle_id:
        return jsonify({"error": "vehicle_id required"}), 400

    # Load all vehicle costs once — reused for both period-filtered metrics
    # and the full-history efficiency calculation
    all_vehicle_costs = [c for c in load_data() if c.get("vehicle_id") == vehicle_id]
    cut = _cutoff(months) if months else None

    costs = all_vehicle_costs
    if cut:
        costs = [c for c in all_vehicle_costs if parse_date_to_iso(c.get("date", "")) >= cut]

    # Defensive sum: skip records whose amount cannot be parsed.
    total_spend = sum(a for a in (_amount(c) for c in costs) if a is not None)

    iso_dates = sorted(parse_date_to_iso(c["date"]) for c in costs if c.get("date"))
    if len(iso_dates) >= 2:
        first = datetime.strptime(iso_dates[0],  "%Y-%m-%d")
        last  = datetime.strptime(iso_dates[-1], "%Y-%m-%d")
        span  = max((last - first).days / 30.44, 1)
        avg_monthly = round(total_spend / span, 2)
    else:
        avg_monthly = total_spend

    fuel_costs       = [c for c in costs if c.get("category") == "Fuel"]
    total_litres     = sum(n for n in (_num(c, "litres") for c in fuel_costs) if n is not None)
    total_fuel_spend = sum(a for a in (_amount(c) for c in fuel_costs) if a is not None)
    avg_ppl = round(total_fuel_spend / total_litres, 3) if total_litres else None

    # Efficiency uses full history (not period-filtered) for correct consecutive pairs
    eff        = _compute_efficiency(all_vehicle_costs, cutoff_date=cut)
    mpg_values = [e["mpg"] for e in eff if e["mpg"] is not None]
    kpl_values = [e["kpl"] for e in eff if e["kpl"] is not None]

    return jsonify({
        "total_spend":  round(total_spend, 2),
        "avg_monthly":  round(avg_monthly, 2),
        "total_litres": round(total_litres, 1),
        "avg_ppl":      avg_ppl,
        "avg_mpg":      round(sum(mpg_values) / len(mpg_values), 1) if mpg_values else None,
        "best_mpg":     round(max(mpg_values), 1) if mpg_values else None,
        "avg_kpl":      round(sum(kpl_values) / len(kpl_values), 2) if kpl_values else None,
        "best_kpl":     round(max(kpl_values), 2) if kpl_values else None,
        "entry_count":  len(costs),
    })


# ── GET /api/reports/monthly ──────────────────────────────────────────────────

@reports_bp.route("/reports/monthly", methods=["GET"])
def report_monthly():
    """
    Monthly spend per category. Every month in range included (zero-filled)
    so the chart never has unexplained gaps.
    """
    vehicle_id = request.args.get("vehicle_id", "")
    months     = int(request.args.get("months", 12))
    if not vehicle_id:
        return jsonify({"error": "vehicle_id required"}), 400

    costs = _filter(vehicle_id, months)

    monthly    = defaultdict(lambda: defaultdict(float))
    categories = set()

    for c in costs:
        if not c.get("date"):
            continue
        amt = _amount(c)
        if amt is None:
            continue
        month = parse_date_to_iso(c["date"])[:7]
        cat   = c.get("category", "Other")
        monthly[month][cat] += amt
        categories.add(cat)

    today      = date.today()
    all_months = []
    if months > 0:
        for i in range(months - 1, -1, -1):
            d = today - relativedelta(months=i)
            all_months.append(d.strftime("%Y-%m"))
    else:
        all_months = sorted(monthly.keys()) if monthly else [today.strftime("%Y-%m")]

    categories = sorted(categories)
    series = {
        cat: [round(monthly[m].get(cat, 0), 2) for m in all_months]
        for cat in categories
    }

    return jsonify({"months": all_months, "categories": categories, "series": series})


# ── GET /api/reports/category ─────────────────────────────────────────────────

@reports_bp.route("/reports/category", methods=["GET"])
def report_category():
    """Total spend per category for the given period."""
    vehicle_id = request.args.get("vehicle_id", "")
    months     = int(request.args.get("months", 0))
    if not vehicle_id:
        return jsonify({"error": "vehicle_id required"}), 400

    costs  = _filter(vehicle_id, months or None)
    totals = defaultdict(float)
    for c in costs:
        amt = _amount(c)
        if amt is None:
            continue
        totals[c.get("category", "Other")] += amt

    sorted_cats = sorted(totals.items(), key=lambda x: x[1], reverse=True)
    return jsonify({
        "categories": [c[0] for c in sorted_cats],
        "totals":     [round(c[1], 2) for c in sorted_cats],
    })


# ── GET /api/reports/efficiency ───────────────────────────────────────────────

@reports_bp.route("/reports/efficiency", methods=["GET"])
def report_efficiency():
    """
    Fuel efficiency series (MPG, km/L, p/litre) per full-tank fill-up.

    Uses full history for consecutive-pair calculation, then filters to
    the requested period for display. Returns record IDs so the frontend
    can match entries by ID rather than fragile date+odometer matching.

    Query params:
      vehicle_id  required
      months      optional — filters displayed results (default: all time)
    """
    vehicle_id = request.args.get("vehicle_id", "")
    months     = int(request.args.get("months", 0))
    if not vehicle_id:
        return jsonify({"error": "vehicle_id required"}), 400

    all_costs = [c for c in load_data() if c.get("vehicle_id") == vehicle_id]
    cut       = _cutoff(months) if months else None
    series    = _compute_efficiency(all_costs, cutoff_date=cut)
    return jsonify(series)


# ── GET /api/reports/cumulative ───────────────────────────────────────────────

@reports_bp.route("/reports/cumulative", methods=["GET"])
def report_cumulative():
    """Running cumulative spend over time for the area/line chart."""
    vehicle_id = request.args.get("vehicle_id", "")
    months     = int(request.args.get("months", 0))
    if not vehicle_id:
        return jsonify({"error": "vehicle_id required"}), 400

    costs = _filter(vehicle_id, months or None)
    costs.sort(key=lambda c: parse_date_to_iso(c.get("date", "")))

    running = 0.0
    points  = []
    for c in costs:
        amt = _amount(c)
        if amt is None:
            continue
        running += amt
        points.append({"date": parse_date_to_iso(c["date"]), "total": round(running, 2)})

    return jsonify(points)


# ── GET /api/reports/costpermile ──────────────────────────────────────────────

@reports_bp.route("/reports/costpermile", methods=["GET"])
def report_cost_per_mile():
    """
    Monthly cost-per-mile using consecutive odometer readings across fills.
    For each month, takes the odometer span from the last fill of the
    previous month to the last fill of this month, then divides total
    monthly spend by that distance. Far more accurate than min/max within
    a single month (which gives 0 when there's only one fill).

    Returns: { months: [...], cpm: [...] }
    """
    vehicle_id = request.args.get("vehicle_id", "")
    months     = int(request.args.get("months", 12))
    if not vehicle_id:
        return jsonify({"error": "vehicle_id required"}), 400

    # Use full history for odometer continuity, filter spend by period
    all_costs = [c for c in load_data() if c.get("vehicle_id") == vehicle_id]
    cut = _cutoff(months) if months else None

    # Build month -> total spend map (filtered to period)
    monthly_spend = defaultdict(float)
    for c in all_costs:
        if not c.get("date"):
            continue
        amt = _amount(c)
        if amt is None:
            continue
        iso = parse_date_to_iso(c["date"])
        if cut and iso < cut:
            continue
        monthly_spend[iso[:7]] += amt

    # Get all fuel entries with a parseable odometer, sorted chronologically
    fuel_odo = []
    for c in all_costs:
        if c.get("category") != "Fuel" or not c.get("date"):
            continue
        odo = _num(c, "odometer")
        if odo is None:
            continue
        fuel_odo.append({**c, "_odo": odo})
    fuel_odo.sort(key=lambda c: parse_date_to_iso(c.get("date", "")))

    if len(fuel_odo) < 2:
        return jsonify({"months": [], "cpm": []})

    # Build month -> last odometer reading map
    month_last_odo = {}
    for c in fuel_odo:
        month = parse_date_to_iso(c["date"])[:7]
        month_last_odo[month] = c["_odo"]

    # Calculate CPM for each month that has spend and an odometer span
    result_months, result_cpm = [], []
    sorted_months = sorted(monthly_spend.keys())

    for month in sorted_months:
        curr_odo = month_last_odo.get(month)
        if curr_odo is None:
            continue

        # Find the last odometer reading from any earlier month
        prev_odo = None
        for earlier in sorted(month_last_odo.keys()):
            if earlier < month:
                prev_odo = month_last_odo[earlier]

        if prev_odo is None or curr_odo <= prev_odo:
            continue

        miles = curr_odo - prev_odo
        if 0 < miles < 5000:  # sanity: ignore implausible monthly mileage
            cpm = monthly_spend[month] / miles
            result_months.append(month)
            result_cpm.append(round(cpm, 4))

    return jsonify({"months": result_months, "cpm": result_cpm})


# ── GET /api/reports/fillinterval ─────────────────────────────────────────────

@reports_bp.route("/reports/fillinterval", methods=["GET"])
def report_fill_interval():
    """
    Days between consecutive fuel fill-ups.
    Reveals changes in vehicle usage pattern (e.g. working from home).

    Returns: { dates: [...], days: [...] }
    """
    vehicle_id = request.args.get("vehicle_id", "")
    months     = int(request.args.get("months", 0))
    if not vehicle_id:
        return jsonify({"error": "vehicle_id required"}), 400

    all_costs = [c for c in load_data() if c.get("vehicle_id") == vehicle_id
                 and c.get("category") == "Fuel"]
    all_costs.sort(key=lambda c: parse_date_to_iso(c.get("date", "")))

    cut = _cutoff(months) if months else None
    dates, days = [], []

    for i in range(1, len(all_costs)):
        iso_curr = parse_date_to_iso(all_costs[i].get("date", ""))
        iso_prev = parse_date_to_iso(all_costs[i-1].get("date", ""))
        if cut and iso_curr < cut:
            continue
        try:
            curr = datetime.strptime(iso_curr, "%Y-%m-%d")
            prev = datetime.strptime(iso_prev, "%Y-%m-%d")
            diff = (curr - prev).days
            if 0 < diff < 120:  # sanity: ignore gaps > 4 months
                dates.append(iso_curr)
                days.append(diff)
        except ValueError:
            continue

    return jsonify({"dates": dates, "days": days})


# ── GET /api/reports/fuelvsother ──────────────────────────────────────────────

@reports_bp.route("/reports/fuelvsother", methods=["GET"])
def report_fuel_vs_other():
    """
    Monthly fuel spend vs all other costs (insurance, service, tax, etc).
    Stacked area chart — shows how fuel dominates and when big services hit.

    Returns: { months: [...], fuel: [...], other: [...] }
    """
    vehicle_id = request.args.get("vehicle_id", "")
    months     = int(request.args.get("months", 12))
    if not vehicle_id:
        return jsonify({"error": "vehicle_id required"}), 400

    costs = _filter(vehicle_id, months)

    fuel_by_month  = defaultdict(float)
    other_by_month = defaultdict(float)

    for c in costs:
        if not c.get("date"):
            continue
        amt = _amount(c)
        if amt is None:
            continue
        month = parse_date_to_iso(c["date"])[:7]
        if c.get("category") == "Fuel":
            fuel_by_month[month]  += amt
        else:
            other_by_month[month] += amt

    today      = date.today()
    all_months = []
    if months > 0:
        for i in range(months - 1, -1, -1):
            d = today - relativedelta(months=i)
            all_months.append(d.strftime("%Y-%m"))
    else:
        all_keys = set(fuel_by_month.keys()) | set(other_by_month.keys())
        all_months = sorted(all_keys) if all_keys else [today.strftime("%Y-%m")]

    return jsonify({
        "months": all_months,
        "fuel":   [round(fuel_by_month.get(m, 0), 2)  for m in all_months],
        "other":  [round(other_by_month.get(m, 0), 2) for m in all_months],
    })


# ── GET /api/reports/annual ───────────────────────────────────────────────────

@reports_bp.route("/reports/annual", methods=["GET"])
def report_annual():
    """
    Year-by-year summary table: total, per-category totals, avg MPG, miles.
    Covers all years with data — not affected by the period selector.

    Returns: { years: [...], rows: [{year, total, categories: {}, avg_mpg, miles}] }
    """
    vehicle_id = request.args.get("vehicle_id", "")
    if not vehicle_id:
        return jsonify({"error": "vehicle_id required"}), 400

    all_costs = [c for c in load_data() if c.get("vehicle_id") == vehicle_id]
    if not all_costs:
        return jsonify({"years": [], "rows": [], "categories": []})

    # Collect all categories present in data
    all_cats = sorted({c.get("category","") for c in all_costs if c.get("category")})

    # Group by year
    yearly = defaultdict(lambda: defaultdict(float))
    for c in all_costs:
        if not c.get("date"):
            continue
        amt = _amount(c)
        if amt is None:
            continue
        year = parse_date_to_iso(c["date"])[:4]
        cat  = c.get("category", "Other")
        yearly[year][cat]     += amt
        yearly[year]["_total"] += amt

    # Miles driven per year from odometer
    fuel_odo = []
    for c in all_costs:
        if c.get("category") != "Fuel":
            continue
        odo = _num(c, "odometer")
        if odo is None:
            continue
        fuel_odo.append((parse_date_to_iso(c.get("date", ""))[:4], odo))
    miles_by_year = {}
    for year, odo in fuel_odo:
        if year not in miles_by_year:
            miles_by_year[year] = [odo, odo]
        else:
            miles_by_year[year][0] = min(miles_by_year[year][0], odo)
            miles_by_year[year][1] = max(miles_by_year[year][1], odo)

    # MPG per year from efficiency series
    eff = _compute_efficiency(all_costs)
    mpg_by_year = defaultdict(list)
    for e in eff:
        if e["mpg"]:
            yr = e["date"][:4]
            mpg_by_year[yr].append(e["mpg"])

    years = sorted(yearly.keys())
    rows  = []
    for year in years:
        miles_range = miles_by_year.get(year)
        miles       = round(miles_range[1] - miles_range[0]) if miles_range else None
        mpg_vals    = mpg_by_year.get(year, [])
        rows.append({
            "year":       year,
            "total":      round(yearly[year]["_total"], 2),
            "categories": {cat: round(yearly[year].get(cat, 0), 2) for cat in all_cats},
            "avg_mpg":    round(sum(mpg_vals)/len(mpg_vals), 1) if mpg_vals else None,
            "miles":      miles,
        })

    return jsonify({"years": years, "rows": rows, "categories": all_cats})
