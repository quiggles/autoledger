"""
tests/test_dates.py
-------------------
Unit tests for ``routes.data.parse_date_to_iso``.

This is the single most failure-prone function in the codebase: LubeLogger is a
UK app exporting DD/MM/YYYY, and getting the format precedence wrong silently
corrupts every downstream date sort and MPG calculation (negative miles,
400+ MPG). These tests lock the contract — see ADR 0001 / ADR 0005.
"""

import pytest

from routes.data import parse_date_to_iso


@pytest.mark.parametrize(
    "raw,expected",
    [
        # Already ISO — passed through untouched.
        ("2024-03-09", "2024-03-09"),
        # UK DD/MM/YYYY — the day-09, month-03 reading is the correct one.
        ("09/03/2024", "2024-03-09"),
        # Ambiguous 01–12 day: must be read DD/MM (UK), NOT MM/DD.
        ("04/03/2024", "2024-03-04"),
        # DD-MM-YYYY dash variant.
        ("09-03-2024", "2024-03-09"),
        # YYYY/MM/DD slash variant.
        ("2024/03/09", "2024-03-09"),
        # Surrounding whitespace is stripped.
        ("  2024-03-09  ", "2024-03-09"),
    ],
)
def test_known_formats_normalise_to_iso(raw, expected):
    assert parse_date_to_iso(raw) == expected


def test_uk_precedence_beats_us_for_unambiguous_day():
    """A day > 12 can only be DD/MM, proving UK precedence is applied."""
    # 25 cannot be a month, so this is unambiguously 25 March 2024.
    assert parse_date_to_iso("25/03/2024") == "2024-03-25"


def test_unparseable_input_returned_stripped_not_raised():
    """Garbage must fall through safely (stripped), never raise."""
    assert parse_date_to_iso("not-a-date") == "not-a-date"
    assert parse_date_to_iso("  weird  ") == "weird"


def test_empty_input_passthrough():
    assert parse_date_to_iso("") == ""
    assert parse_date_to_iso(None) is None


def test_iso_sort_order_is_lexicographic():
    """ISO output must sort correctly as plain strings (relied on everywhere)."""
    raw = ["09/03/2024", "01/01/2020", "31/12/2026"]
    iso = sorted(parse_date_to_iso(d) for d in raw)
    assert iso == ["2020-01-01", "2024-03-09", "2026-12-31"]
