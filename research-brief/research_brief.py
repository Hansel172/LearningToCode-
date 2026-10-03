#!/usr/bin/env python3
"""Research Brief Builder — a 3-agent team (Researcher, Drafter, Fact-Checker)
that turns one question into a sourced explainer.

This is a learning exercise in multi-agent design, not a maintained app — see
README.md for the design reasoning (role definitions, handoff rules,
escalation thresholds) worked out before any of this code was written.

Usage: python research_brief.py "how does CRISPR gene editing work"

Needs ANTHROPIC_API_KEY in the repo root .env — same key already used by
earnings-tracker and macro-tracker.
"""

import os
import re
import sys
from pathlib import Path

import httpx
from dotenv import load_dotenv

REPO_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(REPO_ROOT / ".env")

MODEL = "claude-sonnet-5"
API_URL = "https://api.anthropic.com/v1/messages"
MIN_FINDINGS = 2           # fewer than this -> stop rather than hand the Drafter a thin list
MAX_AUTO_CORRECTIONS = 3   # more than this -> escalate instead of silently patching everything


def _call(payload, api_key, timeout=90):
    r = httpx.post(
        API_URL,
        headers={
            "x-api-key": api_key,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        },
        json=payload,
        timeout=timeout,
    )
    r.raise_for_status()
    return r.json()


def _text_of(response):
    """Concatenates every text block in a reply. The Researcher's response
    interleaves tool_use/tool_result blocks (the web searches it ran) with
    text blocks — this keeps only what Claude actually wrote, which already
    cites real results from the searches it just saw."""
    return "".join(
        b.get("text", "") for b in response.get("content", []) if b.get("type") == "text"
    ).strip()


# ── Researcher ───────────────────────────────────────────────────────────
# The only agent given a tool, not just a prompt — it has to find real,
# checkable sources, not rely on what the model already "knows." Without
# web_search here, "SOURCE: ..." would just be the model's best guess at a
# plausible-sounding citation.
RESEARCHER_PROMPT = """You are the Researcher in a 3-agent team. Your only job is to find \
real, checkable facts that answer the question below — you do not explain, synthesize, or \
write prose. Use web search to find actual sources; never state a fact you haven't found a \
real source for.

Question: {question}

Reply with ONLY a numbered list, one finding per line, in exactly this format:
N. CLAIM: <the fact> | SOURCE: <publication or site name> | URL: <the real url you found it at>

Find at least 3 findings if the question has that much real material available. If you \
genuinely cannot find enough real sources, say so plainly instead of inventing findings to \
hit a count."""


def run_researcher(question, api_key):
    response = _call({
        "model": MODEL,
        "max_tokens": 4096,
        "tools": [{"type": "web_search_20260209", "name": "web_search", "max_uses": 6}],
        "messages": [{"role": "user", "content": RESEARCHER_PROMPT.format(question=question)}],
    }, api_key)
    text = _text_of(response)

    findings = []
    for line in text.splitlines():
        m = re.match(
            r"^\s*\d+\.\s*CLAIM:\s*(.+?)\s*\|\s*SOURCE:\s*(.+?)\s*\|\s*URL:\s*(\S+)\s*$", line)
        if m:
            findings.append({"claim": m.group(1), "source": m.group(2), "url": m.group(3)})
    return findings


def _findings_block(findings):
    return "\n".join(f"- {f['claim']} (source: {f['source']})" for f in findings)


# ── Drafter ──────────────────────────────────────────────────────────────
DRAFTER_PROMPT = """You are the Drafter in a 3-agent team. Turn the findings below into a \
short, plain-English explainer (3-5 short paragraphs) answering the original question. Use \
ONLY these findings — do not add any fact, number, or claim that isn't listed here, even if \
you know something relevant. If the findings don't fully answer the question, say what's \
missing rather than filling the gap yourself.

Question: {question}

Findings:
{findings_block}

Write the explainer now. No preamble, no "Based on the findings" — start directly with the \
substance."""


def run_drafter(question, findings, api_key):
    prompt = DRAFTER_PROMPT.format(question=question, findings_block=_findings_block(findings))
    response = _call({
        "model": MODEL,
        "max_tokens": 1500,
        # Same lesson learned fixing the earnings tracker's Company Story:
        # this is grounded formatting, not reasoning, and Sonnet 5's
        # adaptive thinking is ON by default — those invisible thinking
        # tokens would otherwise compete with max_tokens for no benefit here.
        "thinking": {"type": "disabled"},
        "messages": [{"role": "user", "content": prompt}],
    }, api_key)
    return _text_of(response)


# ── Fact-Checker ─────────────────────────────────────────────────────────
FACT_CHECKER_PROMPT = """You are the Fact-Checker in a 3-agent team. Check the draft below \
against the findings it was supposed to be built from — every claim in the draft must trace \
back to one of these findings.

Findings:
{findings_block}

Draft:
{draft}

For each claim in the draft that doesn't match a finding, decide:
- SMALL issue (auto-correct): the claim overstates certainty, has a slightly wrong \
number/date versus the finding, or is just awkward phrasing — fix it yourself in the \
corrected draft.
- BIG issue (escalate, do not auto-fix): a claim with NO matching finding at all, OR two \
findings that contradict each other and you can't tell which is right.

Reply in exactly this format:

CORRECTED DRAFT:
<the full draft, with only the small issues fixed>

CORRECTIONS MADE: <plain integer count of small issues you fixed, 0 if none>

ESCALATIONS:
<one line per big issue, or "none" if there weren't any>"""


def run_fact_checker(findings, draft, api_key):
    prompt = FACT_CHECKER_PROMPT.format(findings_block=_findings_block(findings), draft=draft)
    response = _call({
        "model": MODEL,
        "max_tokens": 2000,
        "thinking": {"type": "disabled"},
        "messages": [{"role": "user", "content": prompt}],
    }, api_key)
    text = _text_of(response)

    m = re.search(
        r"CORRECTED DRAFT:\s*(.*?)\s*CORRECTIONS MADE:\s*(\d+)\s*ESCALATIONS:\s*(.*)",
        text, re.DOTALL)
    if not m:
        # Model didn't follow the format — show the uncorrected draft rather
        # than silently dropping the whole run. A handoff that can't be
        # parsed is itself worth surfacing, not hiding.
        return draft, ["Fact-Checker's reply didn't match the expected format — "
                       "showing the Drafter's uncorrected output instead."]

    corrected = m.group(1).strip()
    num_corrections = int(m.group(2))
    escalations_text = m.group(3).strip()
    escalations = [] if escalations_text.lower() == "none" else [
        line.strip("- ").strip() for line in escalations_text.splitlines() if line.strip()
    ]

    if num_corrections > MAX_AUTO_CORRECTIONS:
        escalations.append(
            f"{num_corrections} small corrections were needed on this draft (threshold is "
            f"{MAX_AUTO_CORRECTIONS}) — the Drafter may have drifted from the findings more "
            f"than usual here; worth a closer read.")

    return corrected, escalations


def main():
    if len(sys.argv) < 2:
        print('Usage: python research_brief.py "your question"', file=sys.stderr)
        return 1

    question = sys.argv[1]
    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        print("ANTHROPIC_API_KEY not set in .env — can't run without it.", file=sys.stderr)
        return 1

    print(f'Researcher: searching for "{question}"...')
    findings = run_researcher(question, api_key)
    print(f"  found {len(findings)} finding(s)")

    if len(findings) < MIN_FINDINGS:
        print(f"\nNot enough to go on — only {len(findings)} finding(s), need at least "
              f"{MIN_FINDINGS}. Try rephrasing the question or picking something with more "
              f"public material available.")
        return 0

    print("Drafter: writing the explainer...")
    draft = run_drafter(question, findings, api_key)

    print("Fact-Checker: verifying claims against findings...")
    corrected, escalations = run_fact_checker(findings, draft, api_key)

    print("\n" + "=" * 60)
    print("FINAL BRIEF")
    print("=" * 60)
    print(corrected)

    if escalations:
        print("\n" + "=" * 60)
        print(f"⚠ {len(escalations)} issue(s) need your judgment:")
        print("=" * 60)
        for e in escalations:
            print(f"  - {e}")

    print("\n" + "-" * 60)
    print("Sources:")
    for f in findings:
        print(f"  - {f['claim']}\n    {f['source']} — {f['url']}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
