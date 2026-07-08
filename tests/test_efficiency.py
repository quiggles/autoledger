"""
tests/test_efficiency.py
------------------------
Unit tests for the fuel-efficiency maths in ``routes.reports``.

Covers the helpers (`_mpg`, `_kpl`) and the consecutive-fill engine
(`_compute_efficiency`): chronological pairing, the 10–100 MPG sanity gate,
price-per-litre, and the period filter being applied *after* computation so
the previous-fill reference is never lost.
"""

from routes.reports import LITRES_PER_GALLON, _compute_efficiency, _kpl, _mpg

# ── _mpg / _kpl ────────────────────────────────────────────────────────────────

def test_mpg_basic_calculation():
    # 10 gallons (45.4609 L) over 400 miles = 40 MPG.
    assert _mpg(litres=LITRES_PER_GALLON * 10, miles=400) == 40.0


def test_mpg_guards_against_zero_and_negative():
    assert _mpg(litres=0, miles=400) is None
    assert _mpg(litres=45, miles=0) is None
    assert _mpg(litres=45, miles=-10) is None


def test_kpl_conversion():
    # 40 MPG ≈ 14.17 km/L.
    assert _kpl(40) == round(40 * 1.60934 / LITRES_PER_GALLON, 2)


# ── _compute_efficiency ────────────────────────────────────────────────────────

def _fill(date, odo, litres, amount=60.0, full=True):
    """Build a minimal full-tank fuel record."""
    return {
        "id": f"{date}-{odo}",
        "category": "Fuel",
        "is_full_tank": full,
        "date": date,
        "odometer": odo,
        "litres": litres,
        "amount": amount,
    }


def test_first_fill_has_no_mpg():
    """The first fill has no previous reading, so MPG must be None."""
    fills = [_fill("2024-01-01", 1000, 45)]
    res = _compute_efficiency(fills)
    assert len(res) == 1
    assert res[0]["mpg"] is None
    # Price-per-litre is still computed on a standalone fill.
    assert res[0]["ppl"] == round(60.0 / 45, 3)


def test_consecutive_pair_yields_plausible_mpg():
    fills = [
        _fill("2024-01-01", 1000, 45),
        _fill("2024-01-15", 1300, 45),  # 300 miles on ~9.9 gal ≈ 30 MPG
    ]
    res = _compute_efficiency(fills)
    assert res[1]["miles"] == 300.0
    assert 25 <= res[1]["mpg"] <= 35
    assert res[1]["kpl"] is not None


def test_records_sorted_chronologically_regardless_of_input_order():
    """Out-of-order input must not break the previous-fill pairing."""
    fills = [
        _fill("2024-01-15", 1300, 45),
        _fill("2024-01-01", 1000, 45),
    ]
    res = _compute_efficiency(fills)
    # Output is date-sorted; the earlier date comes first and has no MPG.
    assert [r["date"] for r in res] == ["2024-01-01", "2024-01-15"]
    assert res[0]["mpg"] is None
    assert res[1]["mpg"] is not None


def test_implausible_mpg_rejected_by_sanity_bounds():
    """A tiny mileage gap on a full tank would imply absurd MPG → dropped."""
    fills = [
        _fill("2024-01-01", 1000, 45),
        _fill("2024-01-02", 1002, 45),  # 2 miles on 45 L → way under 10 MPG
    ]
    res = _compute_efficiency(fills)
    assert res[1]["mpg"] is None  # outside 10–100 band
    assert res[1]["miles"] == 2.0  # raw distance still reported


def test_backwards_odometer_produces_no_mpg():
    fills = [
        _fill("2024-01-01", 2000, 45),
        _fill("2024-01-15", 1000, 45),  # odometer went backwards
    ]
    res = _compute_efficiency(fills)
    assert res[1]["mpg"] is None


def test_cutoff_filters_display_but_keeps_pairing():
    """
    With a cutoff, the early fill is hidden but must still have served as the
    reference so the later fill keeps its MPG.
    """
    fills = [
        _fill("2024-01-01", 1000, 45),
        _fill("2024-06-01", 1300, 45),
    ]
    res = _compute_efficiency(fills, cutoff_date="2024-03-01")
    assert [r["date"] for r in res] == ["2024-06-01"]
    assert res[0]["mpg"] is not None  # pairing survived the filter


def test_partial_fill_between_full_fills_counted_in_mpg():
    """
    A partial top-up between two full-tank fills still burns fuel over that
    same odometer span. Its litres must be folded into the *next* full-tank
    fill's total, or MPG is computed from too little fuel and comes out
    roughly double what the car actually does (the bug this test guards).
    """
    fills = [
        _fill("2024-01-01", 1000, 45),               # full tank, anchor
        _fill("2024-01-10", 1200, 20, full=False),    # partial top-up
        _fill("2024-01-20", 1400, 45),                # full tank, 400 mi later
    ]
    res = _compute_efficiency(fills)

    # The partial fill gets no result row of its own.
    assert len(res) == 2
    assert res[1]["miles"] == 400.0

    # MPG must reflect ALL fuel used over the 400 miles: the partial's 20L
    # plus the closing full fill's 45L = 65L, not just the 45L.
    expected_litres_used = 20 + 45
    expected_mpg = round(400 / (expected_litres_used / LITRES_PER_GALLON), 2)
    assert res[1]["litres_used"] == expected_litres_used
    assert res[1]["mpg"] == expected_mpg

    # A naive (buggy) calculation using only the closing fill's 45L would
    # yield a visibly higher, implausible MPG for the same distance.
    buggy_mpg = _mpg(45, 400)
    assert res[1]["mpg"] < buggy_mpg


def test_non_full_tank_and_missing_fields_excluded():
    fills = [
        _fill("2024-01-01", 1000, 45, full=False),   # not full tank
        {"id": "x", "category": "Fuel", "is_full_tank": True,
         "date": "2024-02-01", "odometer": 1300, "litres": 0, "amount": 60},  # no litres
        {"id": "y", "category": "Insurance", "is_full_tank": True,
         "date": "2024-03-01", "odometer": 1600, "litres": 45, "amount": 60},  # not fuel
    ]
    assert _compute_efficiency(fills) == []
