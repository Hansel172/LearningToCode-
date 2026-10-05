# Working agreement

## Before building anything new

For a new project, feature, tool, or script — **no code until these three steps
are done.**

**1. Ask these four questions.** Separately, and wait for answers. Don't answer
them yourself.

1. What is the core problem this solves?
2. Who is this for?
3. What does success look like?
4. What should this *not* do?

**2. Summarize back.** Problem, audience, success, non-goals, the approach that
follows, and anything still ambiguous.

**3. Wait for a go-ahead.**

Does not apply to: edits to existing code, bug fixes, questions, research.

## Teaching

Hansel is learning to code and wants the reps, not just the artifacts.

- Explain *why* a choice was made, not just what the code does.
- When he's building to learn, let him write it and review after.
- Flag one thing worth understanding per change, not a narration of everything.

## Project facts

- `.env` is gitignored and must never be committed. `SENDGRID_API_KEY` is used
  by `morning_briefing.py`; the Robinhood credentials are used only by
  `mcp/investing_mcp.py`.
- `morning_briefing.py` runs from GitHub Actions off **`main`**. Changes on a
  feature branch have no effect until they land on `main`.
- Hansel works at a brokerage. Anything that places trades is a compliance
  question, not just a technical one — flag it once, then it's his call.
- `.github/workflows/idea_team.yml` runs Claude Code autonomously, weekly, to
  propose and implement one small improvement to earnings-tracker or
  macro-tracker, then open a PR — it never merges; Hansel always does.
  **Needs a one-time manual setup he has to do himself** (repo admin access,
  can't be scripted): install the Claude GitHub App at
  github.com/apps/claude. Explicitly forbidden from touching `mcp/`,
  `morning_briefing.py`, `stock-screener-agent/`, or
  `weekly-research-prompt.md` — see the workflow file's own prompt for the
  full guardrails. A platform-level safety check refused even researching a
  fully-autonomous (auto-merge, no human review) version of this when it was
  first proposed — that's why it stops at opening a PR.
- `IDEAS.md` is the Idea Team's backlog. It checks "## Open" first and picks
  the top item before inventing its own idea, moving it to "## Done" in the
  same PR it implements it — Hansel can steer what gets built next by just
  adding a line there, no session needed.

