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
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import sec_data
from analyzer import build_analysis, build_valuation

OUT = ROOT.parent / "docs" / "earnings"


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

    companies = []
    for ticker, description in watchlist:
        print(f"\n{ticker}...")
        cik = sec_data.get_cik(ticker)
        if not cik:
            print(f"  not found on SEC EDGAR — skipping")
            companies.append({"ticker": ticker, "description": description,
                               "error": "not found on SEC EDGAR"})
            continue

        quarters = sec_data.get_quarterly_financials(ticker, num_quarters=12)
        if not quarters:
            print(f"  no usable financial data — skipping")
            companies.append({"ticker": ticker, "description": description,
                               "error": "no financial data available"})
            continue

        analysis = build_analysis(ticker, quarters)
        analysis["description"] = description
        analysis["valuation"] = build_valuation(sec_data.get_market_cap(ticker), quarters)
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
