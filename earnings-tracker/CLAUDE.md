# Earnings Tracker

**Read `profile.local.json` before doing position-specific analysis here.**
It holds which tickers are actually held and in what kind of account — it's
gitignored, same reasoning as `macro-tracker/profile.local.json` (see that
project's CLAUDE.md): personal position information doesn't belong in a
public repo, even when the tickers themselves are unremarkable. If it's
missing, ask rather than guessing which companies are "held."

## Two layers, same split as everywhere else in this repo

| Layer | Written by | Where |
|---|---|---|
| Mechanical facts | `analyzer.py`, from SEC/Nasdaq data | `docs/earnings/data.json` (the phone app) |
| Narrative | Claude, given only those facts | `story` field in `data.json`, and `<TICKER>_tracker.md` |

A cron job can compute that gross margin fell 2 points. It cannot decide
what that means for a specific position — that's why the position-tracker
entries exist as a separate step from the mechanical build, same as the
macro tracker's `themes.json` split.

## The Earnings Analyzer framework

`scripts/update_position_trackers.py` runs the framework against a held
position's latest report and appends one entry to `<TICKER>_tracker.md`:

- **vs. consensus** — from Nasdaq's calendar (`analyst_reaction` in
  `data.json`), when available
- **Key metric** — the single most decision-relevant number this quarter,
  chosen by Claude from the already-computed good/bad/ugly facts (never
  asked to introduce a new one)
- **Good / bad / ugly** — same computed facts the phone app shows
- **Guidance** — always reads "not available." SEC filings and Nasdaq's
  calendar don't carry forward-looking statements; that lives in earnings
  calls and press releases, which this tracker doesn't read. Don't let a
  future change quietly start inventing this — if guidance support gets
  added, it needs its own real data source (a transcript API, for
  instance), not a model guessing at what management "probably" said.
- **Position note** — one sentence, given the holding's account/horizon
  context from `profile.local.json`. Explicitly instructed not to
  recommend buying, selling, or holding — explain, don't advise.
- **Trend verdict** — Improving / Weakening / Holding steady, computed in
  Python from red-flag severity and the existing revenue/margin streaks,
  **not** left to the model. This keeps the one-line verdict provably
  consistent with the red flags already shown elsewhere, rather than a
  second, possibly-disagreeing opinion.

## Which tickers get a tracker file

Whatever's in `profile.local.json`'s `holdings` (local) or the
`HOLDING_TICKERS` repo secret, comma-separated (the Action — see
`update_position_trackers.py` for why both exist: the file never reaches
the runner since it's gitignored, so the secret is what the scheduled job
actually reads). Not necessarily the same set as `watchlist.txt`, which
controls the phone app and can include companies you're just watching, not
holding.

## Running it by hand

```bash
python3 earnings-tracker/scripts/build_public.py
python3 earnings-tracker/scripts/update_position_trackers.py path/to/an/older/data.json
```

Needs `ANTHROPIC_API_KEY` in `.env` for the key-metric/position-note lines;
without it, the mechanical facts and trend verdict still get logged.
