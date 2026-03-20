#!/usr/bin/env python3
"""
Re-rank players.json using the composite draft score formula.
No scraping needed — just reads and re-sorts the existing data.

Usage:
    python rerank.py
"""

import json
from pathlib import Path
from archetypes import draft_score

PLAYERS_FILE = Path(__file__).parent / "players.json"


def main():
    if not PLAYERS_FILE.exists():
        print("ERROR: players.json not found. Run scrape.py first.")
        return

    raw = json.loads(PLAYERS_FILE.read_text(encoding="utf-8"))
    players = raw["players"]

    print(f"Re-ranking {len(players)} players with composite draft score...")

    # Score and sort
    for p in players:
        p["draft_score"] = draft_score(p)
    players.sort(key=lambda p: p["draft_score"], reverse=True)

    # Reassign ranks and tiers
    for i, p in enumerate(players):
        p["id"] = i + 1
        p["rank"] = i + 1
        p["tier"] = 1 if i < 15 else (2 if i < 45 else 3)

    raw["players"] = players

    with open(PLAYERS_FILE, "w", encoding="utf-8") as f:
        json.dump(raw, f, indent=2, ensure_ascii=False)

    print(f"Done! Top 10:")
    for p in players[:10]:
        print(f"  #{p['rank']:>4}  {p['draft_score']:>6.1f}  {p['name']:<25} {p['pos']}  {p['school']} ({p.get('conference','')})")


if __name__ == "__main__":
    main()
