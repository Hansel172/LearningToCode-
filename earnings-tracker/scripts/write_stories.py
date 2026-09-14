#!/usr/bin/env python3
"""Adds a short plain-English "story" to each company already written to
docs/earnings/data.json by build_public.py.

This is deliberately a separate step, run after the mechanical build, not
folded into it — same split as the macro tracker's refresh.py (numbers) vs
themes.json (judgment). analyzer.py computes every fact; this script only
narrates facts that already exist. It is never given room to invent a red
flag, a number, or a trend that isn't already in the data — the prompt
hands it the exact same good/bad/ugly/red-flag/streak lines the app itself
renders, and tells it explicitly not to introduce anything beyond them.

Uses httpx directly against the Messages API rather than the anthropic SDK
— this codebase has stayed on httpx alone throughout, and one JSON POST
doesn't justify a second HTTP dependency.

Requires ANTHROPIC_API_KEY in .env (local) or as a GitHub secret (Action).
Skips silently — the rest of the app still ships — if it's absent, since a
missing story is a lesser failure than a broken build.

Usage: write_stories.py [OLD_DATA_JSON]
  OLD_DATA_JSON is the same pre-rebuild snapshot the workflow already takes
  for send_alerts.py. When given, a company whose period_end hasn't changed
  since that snapshot keeps its old story instead of paying for a fresh
  Claude call — the facts driving the story haven't moved, so the story
  wouldn't meaningfully change either. This matters once the schedule runs
  more than once a day: most runs see no new earnings at all, and without
  this every one of those runs would re-narrate the same unchanged numbers.
"""

import json
import os
import sys
from pathlib import Path

import httpx
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
REPO_ROOT = ROOT.parent
DATA_PATH = REPO_ROOT / "docs" / "earnings" / "data.json"

load_dotenv(REPO_ROOT / ".env")

MODEL = "claude-sonnet-5"
API_URL = "https://api.anthropic.com/v1/messages"


def _fmt_pct(v):
    # Matches app.js's fmtPct() exactly — a bare "8.6" with no % sign reads
    # as an ambiguous raw number, not obviously a percentage, to a model
    # with no other context. Caught by printing and reading the actual
    # prompt before ever spending a real API call on it.
    if v is None:
        return "n/a"
    return f"{'+' if v > 0 else ''}{v:.1f}%"


def _metric_line(m):
    if "change_pts" in m:
        return f"{m['metric']}: {m['change_pts']:+.1f} points ({m['from_pct']:.1f}% -> {m['to_pct']:.1f}%)"
    return f"{m['metric']}: {_fmt_pct(m.get('change_pct'))}"


def build_prompt(company):
    period_line = f"Quarter ending {company['period_end']}, compared to {company['compared_to']}"
    if not company.get("is_quarterly_comparison", True):
        # Without this, every figure below reads as a normal quarter-over-
        # quarter change to the model — for a recently-public company like
        # SPCX, "compared to" is actually 365 days earlier, not 90. Missing
        # this would have the story describe a full year of growth as if it
        # happened in one quarter. Caught by checking a real gap case
        # (SPCX) before ever spending an API call on it.
        months = round(company["gap_days"] / 30.4)
        period_line += (f" — NOTE: this spans {company['gap_days']} days (~{months} months), "
                         f"not one quarter. Say so explicitly; do not describe these as "
                         f"quarter-over-quarter changes.")

    lines = [
        f"Company: {company['ticker']} ({company.get('description', '')})",
        period_line,
        "",
        "THE GOOD:",
        *([f"- {_metric_line(m)}" for m in company["good"]] or ["- (nothing)"]),
        "",
        "THE BAD:",
        *([f"- {_metric_line(m)}" for m in company["bad"]] or ["- (nothing)"]),
        "",
        "THE UGLY:",
        *([f"- {_metric_line(m)}" for m in company["ugly"]] or ["- (nothing)"]),
        "",
        "RED FLAGS:",
        *([f"- [{f['severity'].upper()}] {f['flag']}: {f['detail']}" for f in company["red_flags"]]
          or ["- none"]),
    ]

    trend = company.get("trend", {})
    streak_lines = []
    if trend.get("revenue_growth_streak", 0) >= 3:
        streak_lines.append(f"- Revenue has grown for {trend['revenue_growth_streak']} straight quarters.")
    if trend.get("margin_expansion_streak", 0) >= 3:
        streak_lines.append(f"- Gross margin has expanded for {trend['margin_expansion_streak']} straight quarters.")
    if streak_lines:
        lines += ["", "LONGER-TERM TRENDS:", *streak_lines]

    facts = "\n".join(lines)

    return f"""You are writing a short, plain-English summary of one company's quarterly \
earnings for a personal tracking app read by someone who is not a finance professional.

Use ONLY the facts given below. Do not introduce any number, trend, comparison, or claim \
that isn't explicitly stated in this data — if something isn't here, don't mention it.

{facts}

Write 2-4 sentences explaining what happened this quarter and why it matters. Synthesize \
the facts into a coherent narrative rather than just restating the bullet points in \
sentence form. No preamble ("This quarter...", "Overall...") — start directly with the \
substance. Do not give investment advice or say what to do about it — explain, don't \
recommend."""


def call_claude(prompt, api_key):
    r = httpx.post(
        API_URL,
        headers={
            "x-api-key": api_key,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        },
        json={
            "model": MODEL,
            "max_tokens": 300,
            "messages": [{"role": "user", "content": prompt}],
        },
        timeout=30,
    )
    r.raise_for_status()
    blocks = r.json().get("content", [])
    return "".join(b.get("text", "") for b in blocks if b.get("type") == "text").strip()


def _load_old_stories(path):
    """ticker -> (period_end, story) for whatever the previous run already
    wrote, so an unchanged company can keep its existing story instead of
    regenerating an identical one."""
    if not path:
        return {}
    p = Path(path)
    if not p.exists():
        return {}
    data = json.loads(p.read_text())
    return {
        c["ticker"]: (c.get("period_end"), c["story"])
        for c in data.get("companies", [])
        if c.get("story")
    }


def main():
    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        print("ANTHROPIC_API_KEY not set — skipping stories (the rest of the app still ships).")
        return 0

    if not DATA_PATH.exists():
        print(f"{DATA_PATH} doesn't exist — run build_public.py first.", file=sys.stderr)
        return 1

    old_stories = _load_old_stories(sys.argv[1] if len(sys.argv) > 1 else None)

    data = json.loads(DATA_PATH.read_text())
    wrote = 0
    reused = 0

    for company in data.get("companies", []):
        if company.get("error") or company.get("insufficient_data"):
            continue

        old = old_stories.get(company["ticker"])
        if old and old[0] == company["period_end"]:
            company["story"] = old[1]
            reused += 1
            continue

        try:
            prompt = build_prompt(company)
            company["story"] = call_claude(prompt, api_key)
            wrote += 1
            print(f"  {company['ticker']}: wrote story ({len(company['story'])} chars)")
        except Exception as e:
            print(f"  {company['ticker']}: story generation failed — {e}")
            # Leave the company without a "story" key rather than half-write one;
            # the app already renders fine with it absent.

    DATA_PATH.write_text(json.dumps(data, indent=2) + "\n")
    print(f"Wrote {wrote} new stories, reused {reused} unchanged, to {DATA_PATH}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
