# Ideas

A running backlog for the weekly Idea Team (`.github/workflows/idea_team.yml`)
to work through. Add anything here, specific enough to act on — it checks
this file FIRST, before inventing its own idea.

Add new ideas at the bottom of "Open." When the Idea Team implements one, it
moves it to "Done" in the same PR, so this file always reflects what's
actually left.

## Open

- Make each theme's cited `source` field (e.g. "FRED DFF", "Micron FQ4
  FY2026 earnings") an actual link where a real URL exists, so a reader
  can verify any given figure in one tap instead of having to search for
  it themselves. Only link where a genuine source URL is available —
  never fabricate one to make a citation clickable.

- Add a real historical trend chart (not just a single current value) for
  at least one FRED series referenced inside a theme's "Key data" — e.g.
  tapping the CPI or Fed funds rate dataPoint inside the Fed & Rates card
  expands into a line chart of the last 1-2 years. Different from the
  snapshot tiles removed earlier (a static current number) — this answers
  "is this normal historically," visually, which a bare number or even
  the 52-week range can't fully convey.

- Carefully widen `scan_news.py`'s `DEAL_KEYWORDS` list (currently just
  acquire/merger/partnership-style terms) to catch a few more real deal
  patterns (e.g. "invests in," "stake," "licensing deal") — but weigh this
  against the false-positive cost: a 2026-10-17 manual review found 7 of
  10 live `pending_deals` entries were noise from the keyword matching
  already in place. Only add a keyword if it doesn't make that ratio
  worse; this one may turn out not to be worth doing.

- Have the Idea Team periodically re-review EXISTING `pending_deals`
  entries, not just screen new ones — read each article (not just the
  headline) and remove anything that's aged past being useful or reads as
  a false positive on a second look, the same manual process used in the
  2026-10-17 cleanup. Worth deciding whether this belongs as a recurring
  IDEAS.md item re-added periodically, or as its own scheduled check.

## Done

- Highlighted which macro-tracker themes have changed since the user's
  last visit. `app.js`'s new `visitTracking()` reads a per-device
  `localStorage` timestamp (`macroTrackerLastVisit`, nothing server-side —
  consistent with how this app already avoids needing a backend), compares
  each theme's own `verified` date (falling back to `themes.updated`)
  against it, and tags any card verified since then "Updated" while fading
  the rest to 55% opacity (full on hover/focus). On a reader's very first
  visit, with no stored baseline yet, nothing is flagged or dimmed — it
  just records today's date so the *next* visit has something to compare
  against. Dimming only kicks in when at least one card is actually new,
  so "nothing changed since last time" doesn't fade the whole page.
  Documented in `macro-tracker/CLAUDE.md` so a theme's `verified` date
  isn't bumped without a real re-check — doing so would now falsely flag
  it as changed for every returning reader, not just look stale in
  `themes.json`. Verified by reconstructing `macro-tracker/data/live.json`
  and `themes.json` from the live `docs/macro/data.json`, running
  `python3 macro-tracker/scripts/build_public.py`, and diffing the output:
  `app.js`/`styles.css` changed only as intended, `live`/`themes` content
  came back byte-identical, and the script's own `audit()` reported clean
  (`pending_deals` briefly dropped from the rebuilt `data.json`, as
  expected since `build_public.py` has no concept of it — see
  `scan_news.py`'s own comment on this — then the original `data.json`
  was restored rather than committing that loss). Also sanity-checked
  `visitTracking()`'s and `card()`'s logic standalone under Node for a
  first-visit, a later-visit, and the resulting "Updated"/dimmed output.
  (2026-10-18)

- Made macro-tracker's theme cards collapsed by default (headline +
  status badge only), click/tap to expand the full "Key data" /
  "Portfolio impact" / "What to watch" content — same `<details>`/
  `<summary>` disclosure pattern the earnings tracker already uses for
  its own card sections, applied here to the whole card body instead of
  a secondary backup section. Reduces the page to a scannable list of 7
  headlines by default instead of a wall of text, without losing any
  content — everything just moved inside the collapsed region. Verified
  by reconstructing `macro-tracker/data/live.json` and `themes.json`
  from the live `docs/macro/data.json`, running
  `python3 macro-tracker/scripts/build_public.py`, and diffing the
  output: `app.js`/`styles.css` changed only as intended, `data.json`'s
  `live`/`themes` content came back byte-identical, and the script's own
  `audit()` reported clean. (2026-10-18)

- Added a visible "last verified" date on each macro-tracker theme card,
  not just buried in the underlying `themes.json`/`data.json`. Each theme
  now carries its own `verified` field (e.g. `"2026-10-17"`), rendered as
  a small label next to the status badge in `app.js`'s `card()`. Falls
  back to the whole-file `themes.updated` stamp for any theme written
  before this field existed, so nothing renders blank. Backfilled all 7
  current themes to `2026-10-17`, matching the theme-content refresh done
  that same day (see the entry below) — an honest date, not a guess.
  Documented the new field in `macro-tracker/CLAUDE.md`'s "Rules for
  updating themes.json" so future updates (human or Claude) keep setting
  it per-theme rather than letting it go stale again. (2026-10-18)

- Audited every other FRED series macro-tracker uses (`DFF`, `DGS10`,
  `VIXCLS`, `SP500`, `NASDAQCOM`, `DCOILWTICO`, `T10Y2Y`, plus `PPIACO`)
  for the same class of bug just fixed in `CPIAUCSL`'s year-over-year
  calculation (a fixed list offset silently landing on the wrong
  observation when a series has a gap). Result: no live bug — the YoY fix
  already applies generically to every `mode="yoy"` series (so `PPIACO`
  was already covered, not just `CPIAUCSL`), and `_fifty_two_week_range()`
  already filters by actual date rather than list position, so a gap just
  shrinks its window instead of shifting it. The `"level"`/`"spread"`
  modes' day-over-day change is defined as "vs the prior observation," not
  a calendar-anchored comparison, so it has no fixed-offset assumption to
  break. To make this durable rather than a one-time read-through: pulled
  the YoY date-matching logic out of `build()` into its own `_yoy()`
  function (same pattern as `_fifty_two_week_range()`) and added
  `macro-tracker/scripts/test_refresh.py`, which reconstructs the exact
  CPIAUCSL gap scenario synthetically (no network call) and asserts
  `_yoy()` raises instead of silently using the wrong month, plus checks
  `_fifty_two_week_range()` through a gap. **Not yet wired into CI** — the
  Idea Team's GitHub App token doesn't have `workflows` permission, so it
  can't push a change to `.github/workflows/macro_refresh.yml` itself; see
  the PR description for the one step a human needs to paste in by hand to
  actually run this on every scheduled refresh. Runs manually in the
  meantime: `python3 macro-tracker/scripts/test_refresh.py`. (2026-10-18)

- Refresh macro-tracker's theme content (`docs/macro/data.json`'s "themes")
  that's gone stale — some of it dates to July, August, or early September
  and no longer reflects current conditions. Use web search to re-verify
  the real, current facts for each theme (don't just reword what's already
  there), following the existing sourcing discipline in
  `macro-tracker/CLAUDE.md` (cite sources, no padding, explain mechanism
  not just conclusion). Numeric data (`"live"`) already auto-refreshes on
  its own schedule — this is specifically about the written analysis.
  (2026-10-17)
