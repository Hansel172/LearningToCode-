# Macro Tracker

A personal macro dashboard. Seven theme cards, live rates and index levels,
and a date-sorted list of upcoming catalysts. Open it in a browser each
morning.

**No API keys. No accounts. No secrets.** Everything comes from FRED's public
CSV endpoint.

## Run it

```bash
python3 -m pip install httpx          # only dependency
python3 scripts/refresh.py            # fetch data + build the page bundle
open index.html                       # macOS  (Linux: xdg-open index.html)
```

That's it. The page opens straight from disk — no local server needed.

## First-time setup

```bash
cp profile.example.json profile.local.json
```

Fill it in with your holdings and context. It is **gitignored**; the example
template is what gets committed.

## The two layers

| File | Refreshed by | Holds |
|---|---|---|
| `data/live.json` | `scripts/refresh.py` | index levels, rates, CPI, PPI |
| `data/themes.json` | you, or Claude on request | narratives, portfolio impact, catalysts |
| `data/bundle.js` | generated from both | what `index.html` loads |

A cron job can fetch a number. It cannot judge that an 80% rise in DRAM
prices squeezes Apple's margins. So numbers refresh on a timer and the
analysis refreshes when you ask for it.

**Refreshing the analysis:** in Claude Code, from this directory —

> update themes.json

Claude reads `CLAUDE.md` for the rules and `profile.local.json` for your
holdings, researches what changed, and rewrites the file. Then:

```bash
python3 scripts/refresh.py --bundle-only
```

Skip that and the page shows the old analysis. The bundle is generated, not
live.

## Manual refresh

```bash
python3 scripts/refresh.py              # numbers + bundle
python3 scripts/refresh.py --bundle-only  # after hand-editing themes.json
./scripts/daily.sh                      # refresh, then commit the change
```

## Scheduling it

**macOS (launchd):**

```bash
sed -i '' "s|REPLACE_WITH_ABSOLUTE_PATH|$(cd .. && pwd)|" \
  scripts/com.macrotracker.refresh.plist
cp scripts/com.macrotracker.refresh.plist ~/Library/LaunchAgents/
launchctl load ~/Library/LaunchAgents/com.macrotracker.refresh.plist
```

Logs to `/tmp/macrotracker.log`. Unload with `launchctl unload`.

**Linux (cron):** `crontab -e`, then

```
10 7 * * * /absolute/path/to/macro-tracker/scripts/daily.sh >> /tmp/macrotracker.log 2>&1
```

7:10 rather than 7:00 on purpose — FRED publishes on the hour and every
scheduler on earth fires at :00.

## Version history

`daily.sh` commits each refresh so you can diff how the macro view changed
over time. **This requires a private repo.** In the current public one, all
data files are gitignored because they contain holdings, and the script
detects that and skips the commit rather than failing.

To enable it: create a private repo, move this directory into it, and delete
the `macro-tracker/*` lines from the parent `.gitignore`.

## Data sources

All from `fred.stlouisfed.org/graph/fredgraph.csv` — no key required. FRED's
*documented* API at `api.stlouisfed.org` does need one (400 without it); this
CSV endpoint does not.

`SP500` · `NASDAQCOM` · `VIXCLS` · `DCOILWTICO` · `DFF` · `DGS10` ·
`T10Y2Y` · `CPIAUCSL` · `PPIACO`

CPI and PPI arrive as index levels and are converted to year-over-year
percentages before rendering, because "CPI: 332.568" tells you nothing.

`T10Y2Y` (10-year minus 2-year Treasury yield) is the standard yield-curve
inversion signal — negative means short-term rates are above long-term
rates, widely watched as an early recession indicator. It's shown as a
plain level with no day-over-day change, since the sign is the signal, not
the daily wiggle.

**Known limitation:** FRED publishes daily closes, not intraday quotes. Index
levels are last close and can lag by a session. For a dashboard you read in
the morning, that is the correct number — but it is not a live ticker.

Fonts load from Google Fonts, so the first render needs a network connection.
Offline it falls back to system sans and stays perfectly readable.

## Not investment advice

A personal research tool. It explains; it does not recommend.
