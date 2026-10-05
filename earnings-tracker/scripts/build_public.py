#!/usr/bin/env python3
"""Builds the public web app at docs/earnings from watchlist.txt.

Unlike the macro tracker's public build, there's no separate "judgment"
layer to carry forward here — every number and every good/bad/ugly/red-flag
call is computed mechanically from SEC and Nasdaq data by analyzer.py, the
same function the CLI uses. So this script can be re-run from a completely
clean checkout (as the GitHub Action does) and always produces the full,
current picture — nothing needs to persist between runs except this file
itself and watchlist.txt, both of which are plain, non-sensitive, and
committed on purpose.
"""

import json
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import sec_data
from analyzer import build_analysis, build_valuation

OUT = ROOT.parent / "docs" / "earnings"

# How far ahead to flag an upcoming report. Matches the CLI's own `monitor`
# default so "reports soon" means the same thing in both places.
EARNINGS_SOON_DAYS = 14


def next_earnings_map(tickers, days_ahead=EARNINGS_SOON_DAYS):
    """ticker -> {date, days_away, time} for anyone on `tickers` reporting
    within `days_ahead` days, from the same Nasdaq calendar the CLI's
    `monitor` command and the analyst-reaction line already use. One shared
    call across the whole watchlist rather than one per ticker, since
    get_earnings_calendar() already fetches the full window in one pass."""
    calendar = sec_data.get_earnings_calendar(days_ahead=days_ahead)
    today = date.today()
    out = {}
    for d in sorted(calendar):
        for row in calendar[d]:
            sym = row.get("symbol", "").upper()
            if sym in tickers and sym not in out:
                out[sym] = {
                    "date": d,
                    "days_away": (date.fromisoformat(d) - today).days,
                    "time": row.get("time", ""),
                }
    return out


def load_watchlist():
    """Each line is TICKER followed by a short description of the business
    (whitespace-separated, description is everything after the ticker).
    Returns [(ticker, description), ...]; description is "" if a line has
    no text after the ticker."""
    lines = (ROOT / "watchlist.txt").read_text().splitlines()
    entries = []
    for line in lines:
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        parts = line.split(None, 1)
        ticker = parts[0].upper()
        description = parts[1].strip() if len(parts) > 1 else ""
        entries.append((ticker, description))
    return entries


def main():
    watchlist = load_watchlist()
    print(f"Building public app for {len(watchlist)} ticker(s): "
          f"{', '.join(t for t, _ in watchlist)}")

    print(f"\nChecking next {EARNINGS_SOON_DAYS} days for upcoming reports...")
    upcoming = next_earnings_map({t for t, _ in watchlist})
    if upcoming:
        print(f"  reporting soon: {', '.join(sorted(upcoming))}")

    companies = []
    for ticker, description in watchlist:
        print(f"\n{ticker}...")
        cik = sec_data.get_cik(ticker)
        if not cik:
            print(f"  not found on SEC EDGAR — skipping")
            companies.append({"ticker": ticker, "description": description,
                               "error": "not found on SEC EDGAR",
                               "next_earnings": upcoming.get(ticker)})
            continue

        quarters = sec_data.get_quarterly_financials(ticker, num_quarters=12)
        if not quarters:
            print(f"  no usable financial data — skipping")
            companies.append({"ticker": ticker, "description": description,
                               "error": "no financial data available",
                               "next_earnings": upcoming.get(ticker)})
            continue

        analysis = build_analysis(ticker, quarters)
        analysis["description"] = description
        analysis["next_earnings"] = upcoming.get(ticker)
        analysis["valuation"] = build_valuation(sec_data.get_market_cap(ticker), quarters)
        analysis["annual_returns"] = sec_data.get_annual_returns(ticker)
        if not analysis["insufficient_data"]:
            surprise = sec_data.get_earnings_surprise(ticker, analysis["period_end"])
            if surprise and surprise.get("eps"):
                analysis["analyst_reaction"] = {
                    "eps": surprise.get("eps"),
                    "consensus": surprise.get("epsForecast"),
                    "surprise": surprise.get("surprise"),
                }
            n_high = sum(1 for f in analysis["red_flags"] if f["severity"] == "high")
            n_med = sum(1 for f in analysis["red_flags"] if f["severity"] == "medium")
            print(f"  {len(quarters)} quarters, {n_high} high / {n_med} medium flag(s)")
        else:
            print(f"  only {analysis['quarters_available']} quarter(s) — nothing to compare yet")

        companies.append(analysis)

    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "data.json").write_text(json.dumps({"companies": companies}, indent=2) + "\n")
    print(f"\nWrote {OUT / 'data.json'}")


if __name__ == "__main__":
    main()
