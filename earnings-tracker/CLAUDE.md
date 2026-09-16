# Earnings Tracker

**Read `profile.local.json` before doing position-specific analysis here.**
It holds which tickers are actually held and in what kind of account. If
it's missing, ask rather than guessing which companies are "held."

**What's actually kept private, and what isn't.** `<TICKER>_tracker.md` and
`positions_data/<TICKER>.json` are committed and public — the fact that a
tracker file named `NVDA_tracker.md` exists already discloses that NVDA is
held, same as `watchlist.txt` already discloses the watchlist. Gitignoring
`profile.local.json` doesn't undo that; what it actually protects is
*account-level detail* — which kind of account, dollar amounts, anything
beyond the bare ticker. **Never pass `holding_context`'s `account` field
into a Claude prompt or any other path that reaches a committed file** —
`build_analyzer_prompt()` in `update_position_trackers.py` used to do
exactly this (the model would echo "held in a taxable brokerage" straight
into `position_note`, which then landed in the public repo) until it was
caught and fixed. Only `horizon` (e.g. "long-term") is safe to pass through,
since it's true of all three holdings and isn't account-identifying.

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
position's latest report and builds one entry dict — written to
`positions_data/<TICKER>.json` (structured, the source of truth) and
rendered into `<TICKER>_tracker.md` (prose, for reading in the repo).
`scripts/attach_position_history.py` then patches that same JSON history
onto the company's entry in `docs/earnings/data.json`, so the phone app
shows the identical facts under "Your position" on that ticker's card —
one computation, three places it shows up, never three independent
opinions about the same quarter.

Each entry contains:

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
- **Position note** — one sentence on what the quarter implies for a
  long-term holder, given only the horizon from `profile.local.json` (never
  the account type — see the privacy note above). Explicitly instructed not
  to recommend buying, selling, or holding, or to guess at account details —
  explain, don't advise.
- **Trend verdict** — Improving / Weakening / Holding steady, computed in
  Python from red-flag severity and the existing revenue/margin streaks,
  **not** left to the model. This keeps the one-line verdict provably
  consistent with the red flags already shown elsewhere, rather than a
  second, possibly-disagreeing opinion.

## The Company Story framework

`scripts/write_company_stories.py` builds the 11-question "Company Story"
section on every watchlist card (not just held positions) — business
model, customers, moat, leadership, insider ownership, growth potential,
risk, valuation-vs-quality, market cap, the 5-10 year case, and
risk/reward. This is the section the app's reader cares about more than
the numeric good/bad/ugly gates, and it never surfaces share price.

Two of the 11 answers are never left to the model:
- **Insider ownership** is a fixed string ("requires manual research") —
  there's no free, keyless source, and the alternative to admitting that
  is a model quietly inventing a plausible percentage.
- **Market cap** is formatted directly from `sec_data.get_market_cap()`
  (Nasdaq's public quote-summary endpoint) — a real number, nothing for
  the model to add.

Everything else is qualitative by nature (no numeric endpoint answers
"what's the moat"), so it comes from Claude — but grounded in real,
already-computed numbers (`analyzer.build_valuation()`'s trailing P/E and
EV/EBITDA, plus the existing revenue/margin trend) that the prompt hands
it as facts to use as-is, same "use ONLY the facts given" discipline as
`write_stories.py`. See `README.md`'s "The Company Story" section for the
full breakdown, including why EV/EBITDA often reads "not available" (most
companies only tag a discrete quarterly D&A figure in fiscal Q1 — a real
limitation of the underlying SEC data, not a bug here).

Same reuse-on-unchanged-quarter caching as the AI summary, since this is
long-horizon business narrative that shouldn't churn every hourly run.

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
