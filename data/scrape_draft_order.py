#!/usr/bin/env python3
"""
data.scrape_draft_order — current NBA draft order (post-lottery) from
Tankathon's mock page. Team per pick 1-60 -> datasets/draft_order_<year>.json.
Re-run anytime trades move picks.

Usage:
    python -m data.scrape_draft_order
"""

import re
import sys

import requests

from core.config import DATASETS_DIR, SEASON_YEAR
from core.jsonio import save_json

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120.0",
}

TEAM_NAMES = {
    "ATL": "Hawks", "BOS": "Celtics", "BKN": "Nets", "CHA": "Hornets",
    "CHI": "Bulls", "CLE": "Cavaliers", "DAL": "Mavericks", "DEN": "Nuggets",
    "DET": "Pistons", "GSW": "Warriors", "HOU": "Rockets", "IND": "Pacers",
    "LAC": "Clippers", "LAL": "Lakers", "MEM": "Grizzlies", "MIA": "Heat",
    "MIL": "Bucks", "MIN": "Timberwolves", "NOP": "Pelicans", "NYK": "Knicks",
    "OKC": "Thunder", "ORL": "Magic", "PHI": "76ers", "PHX": "Suns",
    "POR": "Trail Blazers", "SAC": "Kings", "SAS": "Spurs", "TOR": "Raptors",
    "UTA": "Jazz", "WAS": "Wizards",
    # Tankathon alt-text variants
    "GS": "Warriors", "NO": "Pelicans", "NY": "Knicks", "SA": "Spurs",
}


def main():
    url = "https://www.tankathon.com/mock_draft"
    t = requests.get(url, headers=HEADERS, timeout=20).text
    picks = []
    for block in re.split(r'<div class="mock-row(?: future)?"[^>]*>', t)[1:]:
        head = block.split("mock-row-player")[0]
        num = re.search(r'mock-row-pick-number">(\d+)', block)
        abbrs = re.findall(r'alt="([A-Z]{2,3})"', head)
        if not num or not abbrs:
            continue
        owner = abbrs[0]                      # first logo = pick owner
        team = TEAM_NAMES.get(owner, owner)
        if len(abbrs) > 1:                    # traded pick: via original team
            team += f" (via {abbrs[1]})"
        picks.append({"pick": int(num.group(1)), "team": team, "abbr": owner})
    picks.sort(key=lambda p: p["pick"])
    out = DATASETS_DIR / f"draft_order_{SEASON_YEAR}.json"
    save_json(out, {"source": url, "picks": picks})
    print(f"{len(picks)} picks -> {out.name}")
    for p in picks[:5]:
        print(f"  {p['pick']:>2} {p['team']}")


if __name__ == "__main__":
    main()
