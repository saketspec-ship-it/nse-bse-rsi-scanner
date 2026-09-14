"""Data-sufficiency guard: exit non-zero if the generated site looks too thin.

Used by CI so a Yahoo-blocked cloud run fails BEFORE publishing, and never
overwrites a good dashboard produced elsewhere.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--min-rows", type=int, default=1000)
    p.add_argument("--min-priced", type=int, default=500)
    p.add_argument("--site", default=str(ROOT / "site" / "data.json"))
    args = p.parse_args()

    path = Path(args.site)
    if not path.exists():
        print(f"FAIL: {path} does not exist", file=sys.stderr)
        return 1
    data = json.loads(path.read_text(encoding="utf-8"))
    rows = len(data)
    priced = sum(1 for d in data if d.get("price") is not None)
    print(f"site rows={rows} priced={priced} "
          f"(need rows>={args.min_rows}, priced>={args.min_priced})")
    if rows < args.min_rows or priced < args.min_priced:
        print("FAIL: insufficient data — not deploying.", file=sys.stderr)
        return 1
    print("OK: data sufficient.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
