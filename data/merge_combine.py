#!/usr/bin/env python3
"""
Attach combine measurements to player records.

For each year with a combine/combine_<year>.json file, find the matching
NCAA player records (players.json for the current season, history/players_<year>.json
for prior years) and stamp a `combine` field on each match.

Usage:
    python merge_combine.py             # all years with combine data
    python merge_combine.py 2024 2025   # subset
"""

import json
import re
import sys
import unicodedata
from pathlib import Path

from core import HISTORY_DIR, PLAYERS_FILE, SEASON_YEAR
from core.config import COMBINE_DIR

CURRENT_YEAR = SEASON_YEAR

COMBINE_FIELDS = (
    "wingspan_in", "height_no_shoes_in", "height_w_shoes_in",
    "standing_reach_in", "hand_length_in", "hand_width_in",
    "weight_lbs", "body_fat_pct",
    "max_vert_in", "standing_vert_in", "lane_agility_s",
    "shuttle_run_s", "three_quarter_sprint_s", "max_bench_reps",
)


from core.names import normalize_name as _norm


def _players_file(year: int) -> Path:
    return PLAYERS_FILE if year == CURRENT_YEAR else HISTORY_DIR / f"players_{year}.json"


def merge_year(year: int) -> tuple[int, int]:
    combine_file = COMBINE_DIR / f"combine_{year}.json"
    players_file = _players_file(year)
    if not combine_file.exists() or not players_file.exists():
        return 0, 0

    combine_data = json.load(open(combine_file, encoding="utf-8"))
    players_data = json.load(open(players_file, encoding="utf-8"))
    players = players_data["players"]
    players_by_full: dict[str, list] = {}
    for p in players:
        players_by_full.setdefault(_norm(p["name"]), []).append(p)

    # Clear any existing combine fields so removed entries don't linger
    for p in players:
        p.pop("combine", None)

    # Combine-driven match: each combine entry maps to at most one player.
    # Use last-initial fallback only when the combine first name is short
    # (≤4 chars, likely a nickname) AND exactly one candidate exists.
    matched = 0
    unmatched: list[str] = []
    for c in combine_data["players"]:
        full = c["norm_name"]
        candidates = players_by_full.get(full, [])
        if not candidates:
            parts = full.split()
            if len(parts) >= 2 and len(parts[0]) <= 4:
                fl, last = parts[0][0], parts[-1]
                candidates = [
                    p for p in players
                    if _norm(p["name"]).endswith(" " + last)
                    and _norm(p["name"]).split()[0].startswith(fl)
                ]
        if len(candidates) == 1:
            candidates[0]["combine"] = {k: c.get(k) for k in COMBINE_FIELDS}
            matched += 1
        else:
            unmatched.append(c["name"])

    json.dump(players_data, open(players_file, "w", encoding="utf-8"),
              indent=2, ensure_ascii=False)
    return matched, len(combine_data["players"])


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    if args:
        years = [int(a) for a in args]
    else:
        years = sorted({
            int(m.group(1))
            for p in COMBINE_DIR.glob("combine_*.json")
            if (m := re.match(r"combine_(\d{4})\.json", p.name))
        })

    if not years:
        print("No combine_<year>.json files found. Run parse_combine.py first.")
        return

    print("Merging combine measurements into player records...")
    for y in years:
        matched, total = merge_year(y)
        if total == 0:
            print(f"  {y}: skipped (no combine or players file)")
        else:
            print(f"  {y}: {matched}/{total} combine players matched to NCAA records")


if __name__ == "__main__":
    main()
