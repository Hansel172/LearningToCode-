# Macro Tracker

A personal macro dashboard. Open it daily; it shows the state of the world
through the lens of one specific portfolio.

**Read `profile.local.json` before doing any analysis work here.** It holds
who this is for and what they own. It is gitignored — see "Why the split"
below — so if it is missing, ask rather than guessing.

## How it works

Two layers, deliberately separated:

| File | Written by | Contains |
|---|---|---|
| `data/live.json` | `scripts/refresh.py`, on a schedule | index levels, rates, CPI, PPI |
| `data/themes.json` | a person, or Claude on request | narratives, portfolio impact, catalysts |
| `data/bundle.js` | generated from both | what the page actually loads |

**The reason for the split:** a cron job can fetch a number. It cannot decide
that an 80% rise in mobile DRAM prices is bad for Apple's margins. Numbers
refresh automatically; judgment gets refreshed when asked.

After editing `themes.json` by hand, run `python3 scripts/refresh.py
--bundle-only` to regenerate the bundle, or the page will show stale analysis.

## Data sources

Everything comes from **FRED's `fredgraph.csv` endpoint** — no API key, no
account, no secrets in this project at all.

Note that FRED's *documented* API at `api.stlouisfed.org` **does** require a
key (returns 400 without one). The CSV graph endpoint does not. That is the
one being used, deliberately.

Series: `SP500`, `NASDAQCOM`, `VIXCLS`, `DCOILWTICO`, `DFF`, `DGS10`,
`T10Y2Y`, `CPIAUCSL`, `PPIACO`.

`T10Y2Y` (10-year minus 2-year Treasury yield) is FRED's own published
spread, not something derived here from `DGS10` and a second series — it
carries no day-over-day change, since a percent change is meaningless for a
value that routinely crosses zero (the whole point of watching it is the
sign: negative means the curve is inverted, a standard recession signal).

CPI and PPI are published as index levels, which mean nothing to a reader, so
`refresh.py` converts them to year-over-year percentages before they reach the
page.

**Tradeoff:** FRED publishes daily closes, not intraday quotes. Index levels
are last close and occasionally one session behind. For a dashboard opened in
the morning, that is the right number.

## The analysis framework

Every theme follows a four-level funnel. Keep this structure when updating
`themes.json`:

1. **Macro** — what happened. Verified facts with figures and named sources.
2. **Sector** — who wins and who loses.
3. **Holdings** — rate each affected position positive / negative / neutral,
   one line of reasoning each. Only list holdings genuinely affected.
4. **Decision** — the concrete catalyst or date to watch.

## Rules for updating themes.json

- **Cite sources for every figure.** No number without provenance.
- **An empty section is information.** If nothing happened in a theme, say so
  and leave it thin. Never pad.
- **Explain the mechanism, not just the conclusion.** "Bad for Apple" is
  useless; "Apple buys mobile DRAM at scale and an 80% input rise compresses
  gross margin" is the product.
- **No recommendations.** Explain what is happening and what it implies. Do
  not say what to buy or sell.
- Status values: `green` positive · `yellow` watch · `red` negative ·
  `orange` active risk · `blue` developing.

## Communication style

Direct, no filler. Explain reasoning rather than stating conclusions. Always
cite sources for data claims.

## Why the split on personal data

This repository is **public**. Holdings, employer, and personal details live
in `profile.local.json`, which is gitignored along with everything in `data/`.

Consequence: the version-history feature — commit on every refresh, so the
macro view can be diffed over time — **only works once this lives in a private
repo**. Until then the code is tracked and the data is not.
