#!/usr/bin/env python3
"""
Re-score historical seasons with the current formula.

Loads each history/players_<year>.json, recomputes draft_score using the
current archetypes.py, re-sorts and re-ranks. Use after editing the formula
to see how the trait-discovery analysis changes.

Usage:
    python -m model.rerank_history             # all available years
    python -m model.rerank_history 2020 2021   # subset
"""

import re
import sys

from core import HISTORY_DIR, load_json, save_json
from data.scrape import assign_ids_ranks
from model.archetypes import draft_score


def rerank_one(year: int) -> bool:
    path = HISTORY_DIR / f"players_{year}.json"
    if not path.exists():
        print(f"  skip {year}: {path.name} not found")
        return False
    data = load_json(path)
    players = data["players"]
    for p in players:
        p["draft_score"] = draft_score(p)
    players.sort(key=lambda p: p["draft_score"], reverse=True)
    assign_ids_ranks(players)  # stable ids + rank/tier
    data["players"] = players
    save_json(path, data)
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
