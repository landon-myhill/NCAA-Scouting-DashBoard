#!/usr/bin/env python3
"""
Re-score historical seasons with the current formula.

Loads each history/players_<year>.json, recomputes draft_score using the
current archetypes.py, re-sorts and re-ranks. Use after editing the formula
to see how the trait-discovery analysis changes.

Usage:
    python rerank_history.py             # all available years
    python rerank_history.py 2020 2021   # subset
"""

import json
import re
import sys
from pathlib import Path

from archetypes import draft_score

HISTORY_DIR = Path(__file__).parent / "history"


def rerank_one(year: int) -> bool:
    path = HISTORY_DIR / f"players_{year}.json"
    if not path.exists():
        print(f"  skip {year}: {path.name} not found")
        return False
    data = json.loads(path.read_text(encoding="utf-8"))
    players = data["players"]
    for p in players:
        p["draft_score"] = draft_score(p)
    players.sort(key=lambda p: p["draft_score"], reverse=True)
    for i, p in enumerate(players):
        p["id"] = i + 1
        p["rank"] = i + 1
        p["tier"] = 1 if i < 15 else (2 if i < 45 else 3)
    data["players"] = players
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"  {year}: re-scored {len(players)} players, top5 = " +
          ", ".join(p['name'] for p in players[:5]))
    return True


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    if args:
        years = [int(a) for a in args]
    else:
        years = sorted({
            int(re.search(r"(\d{4})", f.stem).group(1))
            for f in HISTORY_DIR.glob("players_*.json")
        })
    if not years:
        print("No history/players_*.json found.")
        return
    print(f"Re-ranking historical seasons: {years}")
    for y in years:
        rerank_one(y)


if __name__ == "__main__":
    main()
