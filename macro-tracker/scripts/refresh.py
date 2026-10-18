#!/usr/bin/env python3
"""Refresh the quantitative half of the dashboard.

Only touches NUMBERS — index levels, rates, CPI/PPI. The qualitative half
(what changed, portfolio impact, catalysts) lives in data/themes.json and is
written by a person or by Claude, because judgment is not something a cron
job can produce.

Everything comes from FRED's fredgraph.csv endpoint, which needs no API key
and no account. (Note: FRED's *documented* API at api.stlouisfed.org does
require a key — it returns 400 without one. This CSV endpoint does not.)

That means zero secrets, nothing to rotate, nothing to leak. The tradeoff is
that FRED publishes daily closes rather than intraday quotes, so index levels
are last close, occasionally one session behind. For a dashboard you open in
the morning, that is the correct number anyway.
"""

import csv
import io
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parent.parent
OUT  = ROOT / "data" / "live.json"
URL  = "https://fred.stlouisfed.org/graph/fredgraph.csv?id={sid}"

# id -> (label, unit, mode)
#   level = latest observation, with change vs the prior observation
#   yoy   = percent change against the observation 12 periods back
MARKET = {
    "SP500":      ("S&P 500",   "", "level"),
    "NASDAQCOM":  ("Nasdaq",    "", "level"),
    "VIXCLS":     ("VIX",       "", "level"),
    # Added after the 2026 Iran war disrupted the Strait of Hormuz — WTI
    # moved from the high-$80s to $97+/bbl in under two weeks (see the
    # "Iran Conflict / Strait of Hormuz" theme). Unitless like the other
    # MARKET tiles; the "WTI Crude" label already says what it is, same as
    # how the VIX tile carries no unit either.
    "DCOILWTICO": ("WTI Crude", "", "level"),
}
MACRO = {
    "DFF":      ("Fed funds rate",   "%", "level"),
    "DGS10":    ("10-year Treasury", "%", "level"),
    "CPIAUCSL": ("CPI",              "%", "yoy"),
    "PPIACO":   ("PPI",              "%", "yoy"),
    # 10Y minus 2Y Treasury yield — the standard recession-inversion signal
    # (negative = inverted curve). FRED publishes this spread as its own
    # series rather than requiring it be derived from two others. "spread"
    # mode (not "level"): a day-over-day percent change is meaningless for a
    # value that routinely crosses zero — (0.01 -> -0.01) would compute as a
    # -200% "change" and point the arrow the wrong way. The level itself,
    # sign included, is the whole signal here.
    "T10Y2Y":   ("10Y-2Y spread",    "pp", "spread"),
}


def series(series_id):
    """Return [(date, value)] oldest-first. FRED writes '.' for gaps."""
    r = httpx.get(URL.format(sid=series_id), timeout=30, follow_redirects=True)
    r.raise_for_status()

    rows = []
    for row in csv.reader(io.StringIO(r.text)):
        if len(row) < 2 or not row[0][:1].isdigit():
            continue
        try:
            rows.append((row[0], float(row[1])))
        except ValueError:
            continue
    return rows


def _months_before(d, n):
    """d with n calendar months subtracted, clamped to the last valid day of
    the resulting month (not used here beyond first-of-month FRED dates, but
    correct regardless)."""
    month = d.month - n
    year = d.year + (month - 1) // 12
    month = (month - 1) % 12 + 1
    day = min(d.day, [31, 29 if year % 4 == 0 and (year % 100 != 0 or year % 400 == 0) else 28,
                       31, 30, 31, 30, 31, 31, 30, 31, 30, 31][month - 1])
    return d.replace(year=year, month=month, day=day)


def _fifty_two_week_range(rows):
    """High/low over the trailing 365 days of observations, inclusive of the
    latest point. None for both if there's under a year of history yet (a
    newly-added series) rather than a misleadingly narrow range."""
    latest_date = datetime.strptime(rows[-1][0], "%Y-%m-%d")
    cutoff = latest_date - timedelta(days=365)
    window = [v for d, v in rows if datetime.strptime(d, "%Y-%m-%d") >= cutoff]
    if len(window) < 2:
        return None, None
    return round(max(window), 2), round(min(window), 2)


def _yoy(rows):
    """Percent change vs the observation exactly 12 months before the latest
    one. Returns (value, as_of_date).

    Finding "12 months ago" by date, not by counting back 13 list positions:
    FRED's own CPIAUCSL series has a missing 2025-10-01 observation (confirmed
    live — almost certainly the Oct 2025 government shutdown delaying that
    release), which silently shifted rows[-13] to August instead of September
    and produced a wrong 4.02% instead of the real ~3.72% YoY figure. A fixed
    index offset assumes no gaps ever occur in a government data series; that
    assumption was false for this exact series, caught by a user comparing
    the app's number against BLS's own reported 3.7%. Pulled out as its own
    function (like _fifty_two_week_range) so the exact gap scenario can be
    unit-tested in test_refresh.py without a network call — see that file for
    the audit this guards against."""
    latest_date = datetime.strptime(rows[-1][0], "%Y-%m-%d")
    target = _months_before(latest_date, 12).strftime("%Y-%m-%d")
    by_date = {d: v for d, v in rows}
    latest, prior = rows[-1][1], by_date.get(target)
    if prior is None:
        raise ValueError(f"no observation exactly 12 months before {rows[-1][0]} "
                          f"(looked for {target}) — a real gap, not guessing a substitute")
    if not prior:
        raise ValueError("zero base")
    return round((latest - prior) / prior * 100, 2), rows[-1][0]


def build(series_id, label, unit, mode):
    rows = series(series_id)
    if not rows:
        raise ValueError("no observations")

    # Only meaningful for modes where the displayed value IS the raw series
    # value — "yoy" tiles (CPI/PPI) display a converted rate, so a 52-week
    # range of the underlying index level wouldn't match what's shown.
    week52_high, week52_low = (
        _fifty_two_week_range(rows) if mode in ("level", "spread") else (None, None)
    )

    if mode == "yoy":
        # An index level like CPI 332.568 means nothing to a reader. The rate
        # of change is the story, so convert before it reaches the dashboard.
        value, as_of = _yoy(rows)
        return {
            "label": label,
            "value": value,
            "unit": "%", "note": "year over year",
            "changePct": None,
        }, as_of

    if mode == "spread":
        # No day-over-day delta — see the comment on T10Y2Y above for why a
        # percent change doesn't mean anything for a value that crosses zero.
        latest = rows[-1][1]
        return {
            "label": label,
            "value": round(latest, 2),
            "unit": unit, "note": "last close",
            "changePct": None,
            "fiftyTwoWeekHigh": week52_high,
            "fiftyTwoWeekLow": week52_low,
        }, rows[-1][0]

    latest = rows[-1][1]
    change = None
    if len(rows) >= 2 and rows[-2][1]:
        change = round((latest - rows[-2][1]) / rows[-2][1] * 100, 2)
    return {
        "label": label,
        "value": round(latest, 2),
        "unit": unit, "note": "last close",
        "changePct": change,
        "fiftyTwoWeekHigh": week52_high,
        "fiftyTwoWeekLow": week52_low,
    }, rows[-1][0]


def collect(spec, heading):
    print(heading)
    out, errors = {}, []
    for sid, (label, unit, mode) in spec.items():
        try:
            entry, as_of = build(sid, label, unit, mode)
            entry.update({
                "asOf": as_of,
                "source": f"FRED {sid}",
                "sourceUrl": f"https://fred.stlouisfed.org/series/{sid}",
            })
            out[sid] = entry
            chg = "" if entry["changePct"] is None else f"  ({entry['changePct']:+}%)"
            print(f"  {sid:<10} {entry['value']}{entry['unit']}{chg}  [{as_of}]")
        except Exception as e:
            errors.append(f"{sid}: {e}")
            print(f"  {sid:<10} FAILED — {e}")
    return out, errors


def write_bundle():
    """Emit data/bundle.js so index.html works from file:// directly.

    Browsers block fetch() against file:// for security, which would make a
    double-clickable page unable to read its own JSON. A script tag has no
    such restriction, so the same data is also written as a JS assignment.
    JSON stays the source of truth; this is a generated view of it.
    """
    live   = json.loads((ROOT / "data" / "live.json").read_text())
    themes_path = ROOT / "data" / "themes.json"
    themes = json.loads(themes_path.read_text()) if themes_path.exists() else {}

    bundle = ROOT / "data" / "bundle.js"
    bundle.write_text(
        "// Generated by scripts/refresh.py — do not edit.\n"
        f"window.__LIVE__ = {json.dumps(live, indent=2)};\n"
        f"window.__THEMES__ = {json.dumps(themes, indent=2)};\n"
    )
    print(f"Wrote {bundle}")


def main():
    bundle_only = "--bundle-only" in sys.argv

    if not bundle_only:
        market, market_errors = collect(MARKET, "Market snapshot (FRED)...")
        macro,  macro_errors  = collect(MACRO,  "Macro series (FRED)...")

        OUT.parent.mkdir(parents=True, exist_ok=True)
        OUT.write_text(json.dumps({
            "updated": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "market": market,
            "macro": macro,
            "errors": market_errors + macro_errors,
        }, indent=2) + "\n")
        print(f"\nWrote {OUT}")
    else:
        market = macro = {"skipped": True}

    write_bundle()

    if not market and not macro:
        print("ERROR: no data retrieved", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
