#!/usr/bin/env python3
"""Appends a tight, dated entry to <TICKER>_tracker.md for each held position
that just reported — the Earnings Analyzer framework (what analysts expected,
what happened, the metric that matters, guidance, what it means for the
position, and a trend verdict), as a running log rather than a live dashboard.

This is a companion to the phone app (docs/earnings/), not a replacement.
The app shows every watchlist company as a always-current snapshot; these
files exist so a *held* position has a permanent, appendable paper trail in
git history, in the user's own analysis framework.

Reuses send_alerts.py's diff logic (a ticker counts as "new" only when its
period_end actually changed since the last run) and write_stories.py's
formatting helpers, rather than a third copy of either.

Usage: update_position_trackers.py [OLD_DATA_JSON]
  Same pre-rebuild snapshot the other two scripts already take.

Which tickers are "held" is deliberately never hardcoded or committed:
  - Locally: earnings-tracker/profile.local.json (gitignored — see
    profile.example.json for the shape)
  - In the Action: the HOLDING_TICKERS repo secret, a comma-separated list
    (e.g. "NVDA,AAPL,MSFT")
Personal position information doesn't belong in a public repo any more than
the macro tracker's account/allocation details do — see that project's
CLAUDE.md for the reasoning this follows.
"""

import json
import os
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from dotenv import load_dotenv

from send_alerts import load_companies, find_new_reports
from write_stories import _metric_line, call_claude

ROOT = Path(__file__).resolve().parent.parent
REPO_ROOT = ROOT.parent
DATA_PATH = REPO_ROOT / "docs" / "earnings" / "data.json"

load_dotenv(REPO_ROOT / ".env")

GUIDANCE_NOTE = (
    "Not available — SEC filings and Nasdaq's calendar don't carry "
    "forward-looking statements; would need an earnings-call transcript "
    "or press-release source to add this."
)


def load_holdings():
    """{ticker: {...local context...}} — from profile.local.json if present
    (local/dev use), else HOLDING_TICKERS env var (what the Action has)."""
    local = ROOT / "profile.local.json"
    if local.exists():
        return json.loads(local.read_text()).get("holdings", {})
    env = os.getenv("HOLDING_TICKERS")
    if env:
        return {t.strip().upper(): {} for t in env.split(",") if t.strip()}
    return {}


def compute_verdict(company):
    """Deterministic, computed from the same facts the app already renders —
    not left to the model, so the verdict can never say something the red
    flags and streaks don't already back up."""
    flags = company.get("red_flags", [])
    if any(f["severity"] == "high" for f in flags):
        return "Weakening", "a high-severity red flag this quarter"

    medium = [f for f in flags if f["severity"] == "medium"]
    trend = company.get("trend", {})
    rev_streak = trend.get("revenue_growth_streak", 0)
    margin_streak = trend.get("margin_expansion_streak", 0)

    if len(medium) >= 2:
        return "Weakening", f"{len(medium)} medium-severity red flags"
    if not flags and (rev_streak >= 2 or margin_streak >= 2):
        streak_bits = []
        if rev_streak >= 2:
            streak_bits.append(f"revenue growth streak at {rev_streak}")
        if margin_streak >= 2:
            streak_bits.append(f"margin expansion streak at {margin_streak}")
        return "Improving", ", ".join(streak_bits)
    if not flags:
        return "Holding steady", "clean quarter, no multi-quarter streak yet"
    return "Holding steady", f"{len(medium)} medium flag(s), nothing worse"


def _top_lines(items, n=3):
    if not items:
        return "nothing stood out"
    return "; ".join(_metric_line(m) for m in items[:n])


def build_analyzer_prompt(company, holding_context):
    lines = [
        f"Company: {company['ticker']}",
        f"Quarter ending {company['period_end']}, compared to {company['compared_to']}",
        "",
        "GOOD: " + _top_lines(company["good"]),
        "BAD: " + _top_lines(company["bad"]),
        "UGLY: " + _top_lines(company["ugly"]),
        "RED FLAGS: " + (
            "; ".join(f"[{f['severity'].upper()}] {f['flag']}" for f in company["red_flags"])
            or "none"
        ),
    ]
    reaction = company.get("analyst_reaction")
    if reaction:
        lines.append(f"ANALYST REACTION: EPS {reaction['eps']} vs consensus "
                      f"{reaction['consensus']} ({reaction['surprise']})")
    facts = "\n".join(lines)

    position_line = "Held long-term in a taxable brokerage."
    if holding_context.get("account"):
        position_line = f"Held {holding_context.get('horizon', 'long-term')} in a {holding_context['account']}."

    return f"""Using ONLY the facts below, write exactly two lines in this format,
nothing else — no preamble, no markdown:

KEY METRIC: <the single metric most worth understanding this quarter, and why, in one sentence>
POSITION NOTE: <one sentence on what this means for a position described as: "{position_line}" — explain, do not recommend buying, selling, or holding>

{facts}"""


def _parse_analyzer_reply(text):
    key_metric, position_note = "", ""
    for line in text.splitlines():
        if line.upper().startswith("KEY METRIC:"):
            key_metric = line.split(":", 1)[1].strip()
        elif line.upper().startswith("POSITION NOTE:"):
            position_note = line.split(":", 1)[1].strip()
    if not key_metric and not position_note:
        # Model didn't follow the format — better to show the raw reply than nothing.
        key_metric = text.strip()
    return key_metric, position_note


def build_entry(company, holding_context, api_key):
    reaction = company.get("analyst_reaction")
    consensus_line = (
        f"EPS {reaction['eps']} vs consensus {reaction['consensus']} ({reaction['surprise']})"
        if reaction else "not available this quarter"
    )

    key_metric, position_note = "", ""
    if api_key:
        try:
            reply = call_claude(build_analyzer_prompt(company, holding_context), api_key)
            key_metric, position_note = _parse_analyzer_reply(reply)
        except Exception as e:
            print(f"    analyzer note failed for {company['ticker']}: {e}")

    verdict, reason = compute_verdict(company)
    today = date.today().isoformat()

    lines = [
        f"## {today} — Quarter ending {company['period_end']}",
        "",
        f"- **vs. consensus:** {consensus_line}",
    ]
    if key_metric:
        lines.append(f"- **Key metric:** {key_metric}")
    lines += [
        f"- **Good:** {_top_lines(company['good'])}",
        f"- **Bad:** {_top_lines(company['bad'])}",
        f"- **Ugly:** {_top_lines(company['ugly'])}",
        f"- **Guidance:** {GUIDANCE_NOTE}",
    ]
    if position_note:
        lines.append(f"- **Position:** {position_note}")
    lines.append(f"- **Trend verdict:** {verdict} — {reason}")
    lines.append("")
    return "\n".join(lines)


def append_entry(ticker, period_end, entry):
    path = ROOT / f"{ticker}_tracker.md"
    if not path.exists():
        path.write_text(f"# {ticker} — position tracker\n\n"
                         f"Appended to by `scripts/update_position_trackers.py` each time "
                         f"{ticker} reports. Never overwritten.\n\n")
    # Guards against a duplicate entry if two runs both catch the same new
    # report (e.g. a manual trigger overlapping the schedule) — each run
    # computes independently from its own snapshot, so without this check
    # both would happily append the same quarter twice.
    existing = path.read_text()
    if f"Quarter ending {period_end}" in existing:
        print(f"    {ticker}: already have an entry for {period_end} — skipping duplicate")
        return
    with path.open("a") as f:
        f.write(entry + "\n")


def main():
    holdings = load_holdings()
    if not holdings:
        print("No holdings configured (profile.local.json or HOLDING_TICKERS) — skipping.")
        return 0

    if not DATA_PATH.exists():
        print(f"{DATA_PATH} doesn't exist — run build_public.py first.", file=sys.stderr)
        return 1

    old = load_companies(sys.argv[1]) if len(sys.argv) > 1 else {}
    new = load_companies(DATA_PATH)
    changed = find_new_reports(old, new)

    held_changed = [c for c in changed if c["ticker"] in holdings]
    if not held_changed:
        print("No held position reported since last run — no tracker entries written.")
        return 0

    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        print("ANTHROPIC_API_KEY not set — tracker entries will skip the key "
              "metric / position note (the mechanical facts still get logged).")

    for company in held_changed:
        entry = build_entry(company, holdings.get(company["ticker"], {}), api_key)
        append_entry(company["ticker"], company["period_end"], entry)
        print(f"  {company['ticker']}: appended entry to {company['ticker']}_tracker.md")

    return 0


if __name__ == "__main__":
    sys.exit(main())
