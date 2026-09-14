# Earnings Tracker

Tracks earnings for companies you follow, and flags things worth a second
look when a new quarter comes in.

**No API key.** Everything comes from SEC EDGAR (the companies' own filings)
and Nasdaq's public earnings calendar — both free, no signup.

## Setup

```bash
cd earnings-tracker
pip install -r requirements.txt
```

## The four commands

**Add a company to your watchlist:**
```bash
python earnings_tracker.py add NVDA
```
Pulls 12 quarters of history and saves it to `watchlist_data/NVDA.json`.
Run this once per company before analyzing it.

**Analyze the latest quarter against the stored baseline:**
```bash
python earnings_tracker.py analyze NVDA
```
Prints a report in four sections — THE GOOD, THE BAD, THE UGLY, and RED
FLAGS — comparing the most recent quarter to the one before it.

**See who's reporting soon:**
```bash
python earnings_tracker.py monitor
```
Checks the next 14 days against your whole watchlist.

**Catch up on anyone who just reported:**
```bash
python earnings_tracker.py report
```
Finds anyone on your watchlist who reported in the last 7 days, refreshes
their data, and runs the full analysis on each.

## What counts as a red flag

- Gross margin down more than 2 points quarter over quarter
- Operating expenses growing faster than revenue for two straight quarters
- Free cash flow flipping negative after being positive
- Net income falling while revenue is still growing
- Cash dropping more than 20% in one quarter (worse if debt rose at the same time)
- Debt rising more than 15% in one quarter

## What this can't do

**No forward guidance.** SEC filings report what already happened, not what
a company says will happen next quarter — that lives in earnings calls and
press releases, not the financial statements this tool reads. `analyze`
does show the analyst consensus beat/miss when Nasdaq's calendar has it,
which is the closest available substitute.

**Large, established US companies work best.** SEC's XBRL data is cleanest
for big filers. Very small companies, foreign private issuers, and some
ETFs/trusts don't tag their financials the same way and may come back
mostly empty — `add` will tell you plainly if that happens rather than
guessing.

## Two things worth knowing about how the numbers are built

**Q4 is derived, not filed directly.** Companies almost never file a
standalone fourth-quarter report — only the full year, in the 10-K. Q4 is
calculated as `full year − Q1 − Q2 − Q3` wherever those three are already
known. This works correctly for dollar figures (revenue, net income, cash
flow) because they add up across quarters. It does **not** work for EPS,
since EPS is a per-share ratio and share counts shift quarter to quarter —
so a derived Q4's EPS is left blank rather than shown as a wrong number.

**Tags can change over time.** Companies occasionally switch which SEC
label they file a number under — Microsoft, for instance, reported revenue
under `Revenues` only through 2010, then switched to a longer label
(`RevenueFromContractWithCustomerExcludingAssessedTax`) from 2016 onward.
This tool checks every common label for a concept and merges what it finds,
so a company's older or newer filings are both counted rather than only
whichever tag happens to be tried first.

## The mobile app

There's also a real page — the same analysis, but as something you open on
your phone rather than the terminal. It lives at `docs/earnings/` and
publishes to GitHub Pages, refreshed automatically by
`.github/workflows/earnings_refresh.yml` every hour from 4pm-8pm ET on
weekdays (plus on demand via "Run workflow" in the Actions tab). It checks
hourly through that window rather than once at market close, since a real
report doesn't always land exactly at close.

**Which companies show up** is controlled by `watchlist.txt` — one entry per
line, ticker followed by a short description of the business (e.g. `NVDA
Designs GPUs and AI chips...`), which the app displays on each card. A
different, deliberately public list from the CLI's own `watchlist_data/`
(see Privacy below). The CLI's `analyze` command also looks up a matching
description here if one exists, purely as a bonus — it works fine without one.

**To rebuild it by hand:**
```bash
python earnings-tracker/scripts/build_public.py
```
This reads `watchlist.txt`, runs the exact same comparison logic the CLI
uses (`analyzer.py` — one shared function, so the phone app and the terminal
report can never quietly disagree with each other), and writes
`docs/earnings/data.json`.

**Add to your home screen:** open the page in Safari or Chrome, then use
"Add to Home Screen." It gets its own icon and opens full-screen, no browser
chrome — same as a normal app. It also works offline, showing whatever was
last loaded.

**Share button:** uses your phone's native share sheet (the same one every
app uses) to send the link via Messages, Mail, or anywhere else. Falls back
to copying the link on a browser that doesn't support it.

Unlike the CLI, there's no separate "judgment" step to keep in sync — every
card is computed mechanically from SEC and Nasdaq data, so the Action can
rebuild the whole page from a clean checkout every run.

**Current watchlist:** NVDA, AAPL, MSFT, SPCX, MU, SNDK, WDC, STX. Edit
`watchlist.txt` and re-run `build_public.py` to change it.

### 12-quarter trend

Each card also draws on the full stored history, not just the latest
quarter versus the one before it:

- A revenue sparkline across every quarter on file (up to 12), with the
  most recent point marked in the card's status color.
- A streak note when it's genuinely informative — "revenue has grown for
  N straight quarters" only appears once N reaches 3, since anything less
  just restates what the quarter-over-quarter comparison above it already
  says.
- "Show all N quarters" expands to the full revenue / gross margin / EPS
  table. EPS reads `n/a` on a derived Q4 for the same reason it does
  elsewhere in this tool — see "Q4 is derived, not filed directly" above.

### App icon

`docs/earnings/icon-source.html` is the editable source — a plain SVG (an
upward sparkline with an endpoint dot, the same motif already used on every
card) rendered to `icon-180.png` / `icon-192.png` / `icon-512.png` via a
browser canvas rather than a design tool, so no new dependency was needed.
To change it: edit the SVG in that file, then regenerate the three PNGs at
their exact pixel sizes (rendering each at its native size directly, rather
than scaling one image down, is what keeps the small one crisp).

## Email alerts

You don't have to remember to open the app — an email goes out only when a
tracked company actually reports a new quarter. Silent every other day.

This reuses the same SendGrid setup as `morning_briefing.py` (one email
pipeline, not two) and runs as part of the same scheduled Action that
refreshes the app. Each run snapshots the previously-published data before
rebuilding, then `send_alerts.py` compares old against new — a ticker whose
latest quarter date changed gets an email; nothing else does.

**To test it by hand:**
```bash
python earnings-tracker/scripts/send_alerts.py path/to/an/older/data.json
```

## AI summaries

Each card can carry a short "AI summary" — 2-4 plain-English sentences
explaining what happened that quarter and why, instead of only bullet
lists. `write_stories.py` runs as an extra step in the same scheduled
Action, right after `build_public.py` computes the mechanical numbers.

**It's given the facts, not asked to find them.** The prompt hands it
exactly the same good/bad/ugly/red-flag/streak lines the app itself
renders — nothing more — and tells it explicitly not to introduce any
number or claim beyond them. This keeps a hard line between what's
computed (verifiable, from SEC/Nasdaq) and what's written (synthesized
from those already-verified facts). The app labels it "AI summary" for
the same reason — it's the one part of a card that isn't independently
checkable the way everything else is.

**It skips companies that haven't changed.** With the app refreshing
hourly during the evening earnings window, most runs find nobody new has
reported. `write_stories.py` is handed the same pre-rebuild snapshot
`send_alerts.py` uses, and reuses a company's existing story whenever its
`period_end` hasn't moved since that snapshot — so an unchanged company
costs nothing, and only a company with a genuinely new quarter gets a
fresh Claude call.

**Setup:** create an API key at [console.anthropic.com](https://console.anthropic.com),
then add it as a repo secret named `ANTHROPIC_API_KEY` (same place as the
SendGrid secrets — repo Settings → Secrets and variables → Actions).
Without it, this step skips itself cleanly and the rest of the app ships
as normal — a missing summary is a smaller problem than a broken build.

**To test it by hand** (needs `ANTHROPIC_API_KEY` in `.env`):
```bash
python earnings-tracker/scripts/write_stories.py
```

## Position trackers

For a company you actually hold — not just watch — every report gets logged
following an "Earnings Analyzer" framework: what analysts expected versus
what happened, the one metric most worth understanding that quarter,
guidance (always "not available" — SEC filings don't carry forward-looking
statements), what it means for the position specifically, and a trend
verdict (Improving / Weakening / Holding steady) computed from the same red
flags and streaks shown elsewhere in this repo, not left to the model's
judgment alone. See `CLAUDE.md` in this folder for the full reasoning.

This is written in two places from the same data, so they can't drift apart:

- **In the app itself** — a "Your position" section on that ticker's card,
  showing the last 8 logged entries, most recent first.
- **`<TICKER>_tracker.md`** (e.g. `NVDA_tracker.md`) — the same entries as
  an append-only, human-readable log in the repo, for anyone who'd rather
  read it there or diff it in git history.

**Which tickers get a file** comes from `profile.local.json` (gitignored —
copy `profile.example.json` to create your own) rather than `watchlist.txt`,
since holding a position is a different fact from just watching a company.
In the Action, the same list comes from the `HOLDING_TICKERS` repo secret
(comma-separated, e.g. `NVDA,AAPL,MSFT`) instead, since the gitignored file
never reaches that runner.

Worth being precise about what this does and doesn't hide: `<TICKER>_tracker.md`
and `positions_data/<TICKER>.json` are committed and public, so a file named
`NVDA_tracker.md` already discloses that NVDA is held — gitignoring
`profile.local.json` doesn't undo that. What it actually keeps private is
*account-level* detail: which kind of account, dollar amounts, anything
beyond the bare ticker. The Earnings Analyzer prompt is deliberately never
given the account type for this reason — only "long-term," since it's true
of all three holdings and isn't account-identifying on its own.

**To test it by hand:**
```bash
python earnings-tracker/scripts/update_position_trackers.py path/to/an/older/data.json
```
Run `build_public.py` first so `data.json` reflects the "new" state to
compare against. Without `ANTHROPIC_API_KEY`, the entry still gets written
with every mechanical fact and the trend verdict — just without the key
metric / position note lines.

**How to know it's actually working end to end**, without waiting for a
real earnings report:
1. Open the Actions tab → "Earnings Tracker Refresh" → "Run workflow" to
   trigger it manually — same workflow the schedule uses, so a successful
   manual run is a real test of the whole pipeline.
2. Check the run's logs for each step: "Build public app" should list
   every watchlist ticker, "Update position trackers" should say either
   "No held position reported since last run" (the normal case — nothing
   to log if nobody's held ticker reported) or list which ticker(s) got an
   entry appended, and "Attach position history to the app" should say how
   many tickers it attached history for.
3. To actually see a real entry get written without waiting for a real
   report, temporarily edit a held ticker's line in a copy of `data.json`'s
   snapshot to an older `period_end`, then run `update_position_trackers.py`
   against that copy — this is exactly what the automated test above does.

## Files

| File | What it does |
|---|---|
| `earnings_tracker.py` | The CLI — the four commands above |
| `analyzer.py` | The comparison logic itself — shared by the CLI and the web app |
| `sec_data.py` | Pulls and cleans data from SEC EDGAR and Nasdaq |
| `red_flag_detector.py` | Scans a company's history for the six flags above |
| `data_store.py` | Saves and loads each ticker's data as local JSON (CLI only) |
| `watchlist.txt` | Which companies the *web app* shows — plain, public, committed |
| `scripts/build_public.py` | Builds `docs/earnings/` from `watchlist.txt` |
| `scripts/send_alerts.py` | Emails you only when someone new has reported |
| `scripts/write_stories.py` | Writes the "AI summary" on each card, from facts already computed |
| `scripts/update_position_trackers.py` | Builds an Earnings Analyzer entry for each held position that reported, writes it to `positions_data/<TICKER>.json` and `<TICKER>_tracker.md` |
| `scripts/attach_position_history.py` | Patches `docs/earnings/data.json` with each held ticker's history so the app can show it |
| `watchlist_data/` | Where the *CLI's* tracked companies' data lives (not committed — see below) |
| `positions_data/<TICKER>.json` | Structured position history — the source of truth the app and the `.md` log both render from |
| `<TICKER>_tracker.md` | Running per-position log — committed (numbers only, no account details) |
| `profile.local.json` | Which tickers are held and in what kind of account (not committed — see below) |
| `profile.example.json` | Template showing `profile.local.json`'s shape, with no real data |

## Privacy

Three different personal-data files, three different rules, on purpose:

- **`watchlist_data/*.json`** (the CLI) is gitignored. This is your personal,
  ad hoc research list — whatever you've typed `add TICKER` for — and it's
  nobody's business but yours.
- **`watchlist.txt`** (the web app) is committed and public by design. It's
  a short, deliberate list you chose to publish, and the app itself only
  ever displays public company financials — no personal or account
  information touches it at all, so there's nothing to redact.
- **`profile.local.json`** (which tickers you hold, and in what kind of
  account) is gitignored. This doesn't hide *that* NVDA/AAPL/MSFT are held —
  `NVDA_tracker.md` existing in the repo already makes that plain — it keeps
  the *account-level* detail out: which kind of account, dollar amounts,
  anything beyond the bare ticker. That's also why the Earnings Analyzer
  prompt is only ever given "long-term," never the account type — see
  `CLAUDE.md` for a real bug this caught (the account type was briefly
  leaking into committed position notes before being fixed). The Action
  gets the ticker list a different way (the `HOLDING_TICKERS` secret) so
  the gitignored file never needs to be committed to make the automation
  work.
