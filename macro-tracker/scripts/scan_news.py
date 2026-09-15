#!/usr/bin/env python3
"""Detects — but does not write — M&A and partnership headlines for held
tickers, patching them into docs/macro/data.json as `pending_deals` for a
human (or Claude, when asked) to turn into a real catalyst entry.

Deliberately stops short of full automation. The earnings tracker can
auto-publish because a SEC filing either exists or it doesn't — there's no
judgment call. News is not that clean: a headline can be a rumor, an opinion
piece, or simply wrong. Auto-writing a catalyst's "why it matters" from an
unconfirmed article is exactly the kind of fabrication this whole project has
tried to avoid elsewhere (see the earnings tracker's "no forward guidance"
rule, or CLAUDE.md's "cite sources for every figure" here). So this script's
only job is surfacing candidates; someone still has to look at each one,
verify it independently, and decide whether it's worth a real entry — same
as the NVIDIA/Hugging Face entry in this repo's history, which was verified
against NVIDIA's own announcement before being written up.

Pending entries expire after PENDING_DAYS regardless of whether anyone acted
on them — there's no "mark as reviewed" button on a static page, so aging
out is what keeps this from accumulating forever. If something's worth
keeping, promote it to a real catalyst in the same edit that lets it expire.

Requires NEWS_API_KEY and HOLDING_TICKERS (same secrets already used
elsewhere in this repo — see stock-screener-agent/fundamentals_screener.py
for the same headline-scanning pattern, and the earnings tracker's
update_position_trackers.py for HOLDING_TICKERS). Skips cleanly if either
is missing, so the rest of the refresh still ships.

Usage: scan_news.py [OLD_DATA_JSON]
  OLD_DATA_JSON is a snapshot of docs/macro/data.json taken BEFORE
  build_public.py ran. That's required, not optional, here: build_public.py
  rebuilds data.json from scratch each run (live + themes only — it has no
  concept of pending_deals), so by the time this script runs, the CURRENT
  data.json's pending_deals is already gone. Without the pre-build snapshot,
  every run would show only that day's hits and silently lose the rolling
  window this script is supposed to provide. Same pattern the earnings
  tracker's send_alerts.py / update_position_trackers.py already use.
"""

import json
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import httpx
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
REPO_ROOT = ROOT.parent
DATA_PATH = REPO_ROOT / "docs" / "macro" / "data.json"

load_dotenv(REPO_ROOT / ".env")

PENDING_DAYS = 7
LOOKBACK_DAYS = 2  # runs daily; no need to re-scan further back each time

COMPANY_NAME = {
    "NVDA": "Nvidia",
    "AAPL": "Apple",
    "MSFT": "Microsoft",
}

DEAL_KEYWORDS = [
    "acquire", "acquires", "acquisition", "acquired",
    "merger", "merges",
    "buys", "buyout", "takeover",
    "partnership", "strategic partnership", "joint venture", "teams up",
]


def load_holdings():
    """Ticker -> company name, for whichever tickers are actually held.
    Same HOLDING_TICKERS secret the earnings tracker uses — no reason for a
    second, differently-named list of the same real-world holdings."""
    env = os.getenv("HOLDING_TICKERS")
    if not env:
        return {}
    tickers = [t.strip().upper() for t in env.split(",") if t.strip()]
    return {t: COMPANY_NAME.get(t, t) for t in tickers}


def matches_deal_keyword(text):
    text = text.lower()
    return any(k in text for k in DEAL_KEYWORDS)


def scan_ticker(ticker, company, api_key, since):
    params = {
        "q": f'"{ticker}" OR "{company}"',
        "from": since.strftime("%Y-%m-%d"),
        "sortBy": "publishedAt",
        "pageSize": 20,
        "language": "en",
        "apiKey": api_key,
    }
    resp = httpx.get("https://newsapi.org/v2/everything", params=params, timeout=10)
    resp.raise_for_status()
    articles = resp.json().get("articles", [])

    hits = []
    for a in articles:
        title = a.get("title") or ""
        desc = a.get("description") or ""
        combined = f"{title} {desc}"
        mentions_company = ticker.lower() in combined.lower() or company.lower() in combined.lower()
        if mentions_company and matches_deal_keyword(combined):
            hits.append({
                "ticker": ticker,
                "headline": title,
                "url": a.get("url"),
                "source": (a.get("source") or {}).get("name", "unknown"),
                "publishedAt": a.get("publishedAt"),
                "detectedAt": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            })
    return hits


def main():
    api_key = os.getenv("NEWS_API_KEY")
    if not api_key:
        print("NEWS_API_KEY not set — skipping deal scan (the rest of the refresh still ships).")
        return 0

    holdings = load_holdings()
    if not holdings:
        print("No holdings configured (HOLDING_TICKERS) — skipping deal scan.")
        return 0

    if not DATA_PATH.exists():
        print(f"{DATA_PATH} doesn't exist — run build_public.py first.", file=sys.stderr)
        return 1

    since = datetime.now(timezone.utc) - timedelta(days=LOOKBACK_DAYS)
    new_hits = []
    for ticker, company in holdings.items():
        try:
            hits = scan_ticker(ticker, company, api_key, since)
            new_hits.extend(hits)
            print(f"  {ticker}: {len(hits)} candidate headline(s)")
        except Exception as e:
            print(f"  {ticker}: scan failed — {e}")

    old_snapshot = Path(sys.argv[1]) if len(sys.argv) > 1 else None
    existing = []
    if old_snapshot and old_snapshot.exists():
        existing = json.loads(old_snapshot.read_text()).get("pending_deals", [])

    cutoff = datetime.now(timezone.utc) - timedelta(days=PENDING_DAYS)
    seen_urls = {e["url"] for e in existing}
    kept = [e for e in existing if datetime.fromisoformat(e["detectedAt"]) >= cutoff]
    added = []
    for h in new_hits:
        if h["url"] in seen_urls:
            continue
        seen_urls.add(h["url"])  # also guards against the same article
        added.append(h)          # matching two different held tickers

    current = json.loads(DATA_PATH.read_text())
    current["pending_deals"] = kept + added
    DATA_PATH.write_text(json.dumps(current, indent=2) + "\n")

    print(f"Pending deals: {len(kept)} carried over, {len(added)} new, "
          f"{len(existing) - len(kept)} expired (>{PENDING_DAYS}d old).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
