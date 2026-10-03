# Research Brief Builder

A 3-agent team that turns one question into a sourced explainer. Built as a
learning exercise in multi-agent design — not a maintained app like
`earnings-tracker/` or `macro-tracker/` — using the 8-step build process from
an "AI agent architect" prompt template (Workflow Audit → Agent Opportunity
Scan → Team Design → Role Definition → Handoff Mapping → Prompt Engineering
→ QA & Safety → Launch Plan), worked through step by step before any code
was written.

```bash
python research_brief.py "how does CRISPR gene editing work"
```

Needs `ANTHROPIC_API_KEY` in the repo root `.env` — same key already used by
`earnings-tracker` and `macro-tracker`. Also bills Claude's web search tool
per search (small, but on top of normal token cost) since the Researcher
below needs it.

## The team

**Researcher** — given a question, finds real sources using Claude's web
search tool and returns findings as `CLAIM | SOURCE | URL` lines. It does
not explain or synthesize anything — just gathers and attributes. This is
the one agent given a tool rather than just a prompt, since "find real
sources" is meaningless without an actual way to search.

**Drafter** — turns the Researcher's findings into a plain-English
explainer. Explicitly told to use ONLY those findings, even if the model
"knows" something relevant — a fact not in the findings list doesn't make
it into the draft.

**Fact-Checker** — checks the draft against the findings line by line.
Small issues (overstated certainty, a slightly wrong number) get
auto-corrected. Big issues (a claim with no matching finding at all, or two
findings that contradict each other) get escalated to you instead, along
with the best-effort corrected draft — you see both the attempt and the
concern at once, not just a stalled pipeline.

## Guardrails, decided before any code was written

- **Thin research stops the pipeline.** Fewer than 2 findings and the
  Researcher doesn't hand off to the Drafter at all — a confident-sounding
  explainer written off almost nothing is worse than no explainer.
- **More than 3 auto-corrections escalates too**, even if none of them were
  individually "big." If the Drafter needed that many fixes, something
  drifted upstream and quietly patching it isn't the right call.
- **The Fact-Checker verifies traceability, not truth.** It confirms every
  claim in the draft actually traces back to a finding — it isn't
  re-researching or deciding whether the Researcher's sources were
  themselves good ones. That judgment stays with you.

## How the handoffs actually work

There's no special inter-agent protocol — each agent is just told to reply
in a specific, predictable text shape, and the next step parses that shape
with a regex. `run_fact_checker()`'s parser is the clearest example: if the
model doesn't follow the `CORRECTED DRAFT: / CORRECTIONS MADE: / ESCALATIONS:`
format exactly, the code falls back to the uncorrected draft plus a note
saying the format broke, rather than crashing or silently losing the run.
That's the entire mechanism multi-agent systems use under the hood —
structured text in, structured text out, with a deliberate plan for when a
reply doesn't come back the way you asked for it.
