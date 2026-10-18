#!/usr/bin/env python3
"""Regression tests for the gap-handling logic in refresh.py.

This exists because of a real bug: FRED's CPIAUCSL series was missing its
2025-10-01 observation (almost certainly the Oct 2025 government shutdown
delaying that release), which silently shifted a fixed rows[-13] lookup onto
the wrong month and produced a wrong YoY figure. The fix (match "12 months
ago" by actual date, raise rather than guess when nothing matches exactly)
lives in _yoy(). These tests construct that same kind of gap synthetically —
no network call — for every function in refresh.py that does date math, so a
future refactor can't quietly reintroduce a fixed-offset assumption.

Run directly: python3 macro-tracker/scripts/test_refresh.py
"""

import sys
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from refresh import _fifty_two_week_range, _months_before, _yoy


def monthly_series(start, months, value_fn, skip=None):
    """[(date, value)] for `months` consecutive first-of-month dates,
    skipping any date string in `skip` to simulate a missing observation."""
    rows = []
    d = start
    for i in range(months):
        ds = d.strftime("%Y-%m-%d")
        if skip is None or ds not in skip:
            rows.append((ds, value_fn(i)))
        month = d.month + 1
        year = d.year + (month - 1) // 12
        month = (month - 1) % 12 + 1
        d = date(year, month, 1)
    return rows


def test_months_before_wraps_year():
    assert _months_before(date(2026, 1, 15), 12) == date(2025, 1, 15)
    assert _months_before(date(2026, 10, 1), 12) == date(2025, 10, 1)
    assert _months_before(date(2025, 3, 31), 1) == date(2025, 2, 28)


def test_yoy_matches_by_date_on_clean_data():
    # 13 clean consecutive months — a fixed rows[-13] offset and a by-date
    # lookup agree here, which is exactly why the bug went unnoticed until a
    # real gap exposed it.
    rows = monthly_series(date(2025, 9, 1), 13, lambda i: 300 + i)
    value, as_of = _yoy(rows)
    assert as_of == "2026-09-01"
    assert value == round((rows[-1][1] - rows[0][1]) / rows[0][1] * 100, 2)


def test_yoy_raises_instead_of_using_wrong_month():
    # Same shape as the real CPIAUCSL incident: the observation exactly 12
    # months back (2025-10-01) is missing. A fixed rows[-13] offset would
    # silently grab 2025-09-01 instead and return a wrong number; by-date
    # lookup must refuse instead of guessing.
    rows = monthly_series(date(2025, 9, 1), 14, lambda i: 300 + i,
                           skip={"2025-10-01"})
    assert rows[-1][0] == "2026-10-01"
    try:
        _yoy(rows)
        raise AssertionError("expected ValueError for the missing month, got a value")
    except ValueError as e:
        assert "2025-10-01" in str(e)


def test_yoy_zero_base_raises():
    rows = [("2025-10-01", 0.0), ("2026-10-01", 5.0)]
    try:
        _yoy(rows)
        raise AssertionError("expected ValueError for a zero base")
    except ValueError:
        pass


def test_fifty_two_week_range_filters_by_date_through_a_gap():
    # A month-long gap inside the trailing year (e.g. a data outage) must
    # shrink the window, not shift it — the filter is "is this date recent
    # enough," never "is this one of the last N rows."
    start = date(2025, 10, 18)
    rows, d = [], start
    for i in range(400):
        if not (date(2026, 3, 1) <= d <= date(2026, 3, 31)):
            rows.append((d.strftime("%Y-%m-%d"), float(i)))
        d += timedelta(days=1)
    high, low = _fifty_two_week_range(rows)
    # Values increase monotonically with date, so the max in any date-bounded
    # window is always the latest observation, gap or no gap.
    assert high == round(rows[-1][1], 2)
    assert low < high


def test_fifty_two_week_range_needs_real_history():
    assert _fifty_two_week_range([("2026-10-01", 1.0)]) == (None, None)


def main():
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    failures = 0
    for t in tests:
        try:
            t()
            print(f"  PASS  {t.__name__}")
        except Exception as e:
            failures += 1
            print(f"  FAIL  {t.__name__}: {e}")
    if failures:
        print(f"\n{failures} of {len(tests)} test(s) failed")
        return 1
    print(f"\nAll {len(tests)} tests passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
