#!/usr/bin/env python3
"""
Attach HS recruit ranks to player records.

Reads all recruits/recruits_<year>.json files, builds a name → best-rank
lookup, and stamps `recruit_rank` (with `recruit_class_year`) onto every
matching player in players.json and each history/players_<year>.json.

Usage:
    python merge_recruits.py
"""

import json
import re
import sys
import unicodedata
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

ROOT = Path(__file__).parent
RECRUITS_DIR = ROOT / "recruits"
HISTORY_DIR = ROOT / "history"
CURRENT_YEAR = 2026


def _norm(name):
    name = unicodedata.normalize("NFKD", name or "")
    name = "".join(c for c in name if not unicodedata.combining(c))
    name = name.lower().strip()
    name = re.sub(r"\s+(jr|sr|ii|iii|iv|v)\.?$", "", name)
    name = re.sub(r"[^\w\s]", "", name)
    return re.sub(r"\s+", " ", name)


def _player_files() -> list[Path]:
    files = [ROOT / "players.json"]
    files.extend(sorted(HISTORY_DIR.glob("players_*.json")))
    return files


def main():
    # Build the recruit lookup: prefer the smallest (best) rank seen across years
    lookup: dict[str, dict] = {}
    for f in sorted(RECRUITS_DIR.glob("recruits_*.json")):
        d = json.load(open(f, encoding="utf-8"))
        for r in d["recruits"]:
            n = r["norm_name"]
            existing = lookup.get(n)
            if existing is None or r["espn_rank"] < existing["espn_rank"]:
                lookup[n] = {
                    "espn_rank": r["espn_rank"],
                    "hs_class_year": r["hs_class_year"],
                }
    print(f"Recruit lookup built: {len(lookup)} unique HS recruits across all classes")

    # Stamp onto every player file
    total_matched = 0
    for pf in _player_files():
        if not pf.exists(): continue
        data = json.load(open(pf, encoding="utf-8"))
        matched = 0
        for p in data["players"]:
            r = lookup.get(_norm(p["name"]))
            if r:
                p["recruit_rank"] = r["espn_rank"]
                p["recruit_class_year"] = r["hs_class_year"]
                matched += 1
            else:
                p.pop("recruit_rank", None)
                p.pop("recruit_class_year", None)
        json.dump(data, open(pf, "w", encoding="utf-8"),
                  indent=2, ensure_ascii=False)
        print(f"  {pf.name}: matched {matched} players with recruit rank")
        total_matched += matched

    print(f"\nTotal recruit-rank attachments: {total_matched}")


if __name__ == "__main__":
    main()
