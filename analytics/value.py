#!/usr/bin/env python3
"""
analytics.value — position-relative NBA career value (the outcome metric).

Why this exists: raw VORP/WS/games misgrade roles. Durable backup bigs farm
Win Shares and games played (Nick Richards: 305 G -> "starter" under the old
games>=300 rule), high-usage guards farm VORP, and a 3-season career (2023
class) can't be compared to a 6-season one (2020) on raw totals.

The fix, in two moves:
  1. RATES, not totals — every ingredient is per-season-since-draft
     (VORP/yr, WS/yr, games/yr) or already a rate (WS/48, BPM).
  2. POSITION-RELATIVE — each ingredient is percentiled WITHIN position
     group (G / F / C), so every career is graded against players asked
     to do the same job.

nba_value = mean of the component percentiles (0..1). Career tiers are bands
on that score (plus a hard games floor for no_nba/bench), replacing the old
absolute thresholds in data/scrape_draft_results.career_tier.

Usage:
    python -m analytics.value              # preview tier changes (no writes)
    python -m analytics.value --rescore    # rewrite career_tier + nba_value
                                           # in datasets/history result files
"""

import json
import sys

from core import HISTORY_DIR, SEASON_YEAR, load_json, save_json
from core.config import MATURE_DRAFT_YEARS
from core.names import match_player, normalize_name

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

# Component weights — BOX-SCORE production + role, no impact composites.
# VORP/WS/BPM are deliberately excluded: they're team-context-dependent
# (starters on bad teams grade as benchwarmers, efficient sixth men grade as
# stars — the Pritchard problem). What we grade instead:
#   production  — career PPG / RPG / APG, percentiled within position group
#   role (MPG)  — minutes per game: the coach-revealed answer to "is he a
#                 starter?" — nobody gives 32 minutes to a bench player
#   durability  — games per season since draft
RATE_WEIGHTS = {
    "ppg": 0.35,
    "mpg": 0.25,
    "rpg": 0.15,
    "apg": 0.15,
    "games_rate": 0.10,
}
RATE_KEYS = tuple(RATE_WEIGHTS)

# Tier bands on the position-relative value score. Calibrated against known
# careers (preview in __main__): impact composites punish starters on bad
# teams (Sochan, Ivey), so the rotation floor is deliberately forgiving.
TIER_BANDS = (
    ("star", 0.90),
    ("starter", 0.72),
    ("rotation", 0.32),
    ("bench", 0.0),
)


def pos_group(college_pos: str) -> str:
    return college_pos if college_pos in ("G", "F", "C") else "F"


def career_rates(career: dict, seasons: int) -> dict | None:
    """Box-score rates for one career. None if he basically never played."""
    games = career.get("games") or 0
    if games < 10:
        return None  # no_nba territory — rates meaningless
    seasons = max(1, seasons)
    minutes = career.get("minutes") or 0
    return {
        "ppg": career.get("PPG"),
        "rpg": career.get("RPG"),
        "apg": career.get("APG"),
        "mpg": minutes / games if games else None,
        "games_rate": games / seasons,
    }


def _percentile_ranks(values):
    """values may contain None -> stays None. Average-rank ties -> [0,1]."""
    idx = [i for i, v in enumerate(values) if v is not None]
    out = [None] * len(values)
    if not idx:
        return out
    order = sorted(idx, key=lambda i: values[i])
    n = len(order)
    i = 0
    while i < n:
        j = i
        while j + 1 < n and values[order[j + 1]] == values[order[i]]:
            j += 1
        pct = ((i + j) / 2.0) / (n - 1) if n > 1 else 0.5
        for k in range(i, j + 1):
            out[order[k]] = pct
        i = j + 1
    return out


def attach_position_value(entries: list[dict], asof_year: int = SEASON_YEAR,
                          by_position: bool = True) -> None:
    """Compute entry['nba_value'] (0..1 or None) for a population of careers.

    Each entry needs: 'career' (dict), 'year' (draft year), 'pos' (college
    G/F/C). Percentiles are computed within position group across the WHOLE
    population passed in — call once with all classes pooled.

    by_position=False pools all positions together — use for single-class
    early-career tracking, where per-position groups are too small (~8
    centers) and topping a tiny group prints a meaningless 1.00.
    """
    for e in entries:
        e["_rates"] = career_rates(e.get("career") or {}, asof_year - e["year"])

    groups = ("G", "F", "C") if by_position else ("all",)
    for grp in groups:
        members = (entries if grp == "all" else
                   [e for e in entries if pos_group(e.get("pos", "")) == grp])
        if not members:
            continue
        pcts_by_key = {
            k: _percentile_ranks([(m["_rates"] or {}).get(k) for m in members])
            for k in RATE_KEYS
        }
        for i, m in enumerate(members):
            if m["_rates"] is None:
                m["nba_value"] = 0.0  # never really played — floor outcome
                continue
            parts = [(RATE_WEIGHTS[k], pcts_by_key[k][i])
                     for k in RATE_KEYS if pcts_by_key[k][i] is not None]
            wsum = sum(w for w, _ in parts)
            m["nba_value"] = sum(w * v for w, v in parts) / wsum if wsum else None

    for e in entries:
        e.pop("_rates", None)


# Quality floors for the top tiers (WS/48 rate; league avg ~.100,
# replacement ~.045). Box-score tiers alone counted ATTAINING a starter's
# role as success: Keyonte George graded "star" at WS/48 .032 — below
# replacement. The floor demotes empty-volume roles; the value SCORE itself
# stays pure box-score per the project's grading rule.
_STAR_WS48 = 0.075
_STARTER_WS48 = 0.040


def value_tier(nba_value, career: dict) -> str:
    games = (career or {}).get("games") or 0
    if games < 10:
        return "no_nba"
    if nba_value is None or nba_value == 0.0:
        return "bench"
    tier = "bench"
    for t, floor in TIER_BANDS:
        if nba_value >= floor:
            tier = t
            break
    ws48 = (career or {}).get("WS/48")
    if ws48 is not None:
        if tier == "star" and ws48 < _STAR_WS48:
            tier = "starter"
        if tier == "starter" and ws48 < _STARTER_WS48:
            tier = "rotation"
    return tier


# ── Rescoring the stored result files ────────────────────────────────────────

def _college_pos_lookup(year: int) -> dict:
    """norm_name -> college pos for one draft class, via the history file."""
    path = HISTORY_DIR / f"players_{year}.json"
    if not path.exists():
        return {}
    players = load_json(path)["players"]
    by_norm = {normalize_name(p["name"]): p for p in players}
    by_school: dict = {}
    for p in players:
        by_school.setdefault(p.get("school", ""), []).append(p)
    return {"by_norm": by_norm, "by_school": by_school}


def _collect_entries(years):
    """Pool drafted (+ undrafted, when scraped) careers across classes."""
    entries = []
    for y in years:
        lookup = _college_pos_lookup(y)
        for kind, fname, name_key in (("drafted", f"draft_results_{y}.json", "player"),
                                      ("undrafted", f"undrafted_results_{y}.json", "player")):
            path = HISTORY_DIR / fname
            if not path.exists():
                continue
            data = load_json(path)
            rows = data.get("picks") or data.get("players") or []
            for r in rows:
                pos = ""
                if lookup:
                    rec = match_player({"player": r.get(name_key, ""),
                                        "college": r.get("college", "")},
                                       lookup["by_norm"], lookup["by_school"])
                    pos = (rec or {}).get("pos", "")
                entries.append({"kind": kind, "year": y, "row": r,
                                "career": r.get("career") or {}, "pos": pos,
                                "file": path, "data": data})
    return entries


YOUNG_CLASSES = (2024, 2025)


def _grade(entries, rescore, changes):
    attach_position_value(entries)
    for e in entries:
        old = e["row"].get("career_tier", "?")
        new = value_tier(e.get("nba_value"), e["career"])
        if rescore:
            e["row"]["career_tier"] = new
            e["row"]["nba_value"] = round(e["nba_value"], 3) if e.get("nba_value") is not None else None
        if old != new:
            changes.append((e["year"], e["row"].get("player"), e["pos"], old, new,
                            e.get("nba_value")))
    return entries


def main():
    rescore = "--rescore" in sys.argv
    changes, all_entries = [], []

    # Mature classes: pooled percentiles (careers of comparable length)
    entries = _collect_entries(list(MATURE_DRAFT_YEARS))
    print(f"Pooled {len(entries)} mature careers "
          f"({sum(1 for e in entries if e['kind'] == 'undrafted')} undrafted)")
    all_entries += _grade(entries, rescore, changes)

    # Young classes: graded WITHIN their own class — a 1-season career can't
    # pool with 6-season ones, but vs his own class peers the comparison is
    # honest, so Flagg-types get a real tier instead of "early career".
    for y in YOUNG_CLASSES:
        e = _collect_entries([y])
        if e:
            print(f"{y}: {len(e)} careers graded within-class")
            all_entries += _grade(e, rescore, changes)

    print(f"\nTier changes: {len(changes)}")
    for y, name, pos, old, new, val in sorted(changes, key=lambda c: -(c[5] or 0)):
        v = f"{val:.2f}" if val is not None else " n/a"
        print(f"  {y} {name:<26} {pos or '?'}  {old:>9} -> {new:<9} (value {v})")

    if rescore:
        for path in {str(e["file"]) for e in all_entries}:
            datas = [e["data"] for e in all_entries if str(e["file"]) == path]
            save_json(HISTORY_DIR / path.split("\\")[-1].split("/")[-1], datas[0])
        print(f"\nRewrote career_tier + nba_value in {len({str(e['file']) for e in entries})} files.")
    else:
        print("\n(preview only — run with --rescore to write)")


if __name__ == "__main__":
    main()
