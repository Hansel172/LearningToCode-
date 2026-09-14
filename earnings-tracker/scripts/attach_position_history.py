#!/usr/bin/env python3
"""Attaches each held ticker's persisted position history (positions_data/
<TICKER>.json, written by update_position_trackers.py) onto its entry in
docs/earnings/data.json, as company["position_history"].

Runs as the last content step, after update_position_trackers.py, so a
brand-new entry from THIS run shows up in the app immediately rather than
waiting for the next refresh. build_public.py can't do this itself — it
runs first, before the current run knows whether anyone just reported.

Every held ticker gets its full persisted history reattached every run
(not just ones that reported today), since build_public.py rebuilds
data.json from scratch each time and carries nothing forward on its own.
"""

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
REPO_ROOT = ROOT.parent
DATA_PATH = REPO_ROOT / "docs" / "earnings" / "data.json"
POSITIONS_DIR = ROOT / "positions_data"

# Shown most-recent-first, and capped — this is a companion history, not a
# replacement for the 12-quarter trend the card already shows.
MAX_ENTRIES = 8


def main():
    if not DATA_PATH.exists():
        print(f"{DATA_PATH} doesn't exist — run build_public.py first.", file=sys.stderr)
        return 1
    if not POSITIONS_DIR.exists():
        print("No positions_data/ — nothing to attach.")
        return 0

    data = json.loads(DATA_PATH.read_text())
    attached = 0
    for company in data.get("companies", []):
        path = POSITIONS_DIR / f"{company['ticker']}.json"
        if not path.exists():
            continue
        entries = json.loads(path.read_text()).get("entries", [])
        if not entries:
            continue
        company["position_history"] = list(reversed(entries))[:MAX_ENTRIES]
        attached += 1

    if attached:
        DATA_PATH.write_text(json.dumps(data, indent=2) + "\n")
    print(f"Attached position history for {attached} ticker(s).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
