#!/usr/bin/env python3
"""
Re-rank players.json using the composite draft score formula.
No scraping needed — just reads and re-sorts the existing data.

Usage:
    python rerank.py
"""

import json
from pathlib import Path
from archetypes import draft_score, classify

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

    # Pre-compute archetype profiles so the app doesn't need to classify at runtime
    print("Classifying player archetypes...")
    for p in players:
        profile = classify(p)
        p["archetype"] = profile["primary"]
        p["defensive_archetype"] = profile["defensive"]
        p["all_offensive"] = profile["all_offensive"]
        p["all_defensive"] = profile["all_defensive"]
        p["tags"] = profile["tags"]
        p["red_flags"] = profile["red_flags"]

    raw["players"] = players

    with open(PLAYERS_FILE, "w", encoding="utf-8") as f:
        json.dump(raw, f, indent=2, ensure_ascii=False)

    print(f"Done! Top 10:")
    for p in players[:10]:
        print(f"  #{p['rank']:>4}  {p['draft_score']:>6.1f}  {p['name']:<25} {p['pos']}  {p['school']} ({p.get('conference','')})")
        print(f"         {p['archetype']} / {p['defensive_archetype']}")

    # ── Pre-compute scarcity data for top 200 ─────────────────────────────────
    print("Building scarcity data...")
    top200 = players[:200]

    # Count ALL archetypes each player qualifies for (not just primary)
    arch_counts = {}   # archetype → {1: n, 2: n, 3: n}
    arch_scores = {}   # archetype → [scores]
    arch_top = {}      # archetype → best player name/rank
    arch_type = {}     # archetype → "offensive" or "defensive"

    for p in top200:
        t = p["tier"]
        score = p.get("draft_score", 0)

        # Count all offensive archetypes
        for arch in p.get("all_offensive", []):
            if not arch:
                continue
            if arch not in arch_counts:
                arch_counts[arch] = {1: 0, 2: 0, 3: 0}
                arch_scores[arch] = []
                arch_top[arch] = {"rank": p["rank"], "name": p["name"]}
                arch_type[arch] = "offensive"
            arch_counts[arch][t] += 1
            arch_scores[arch].append(score)
            if p["rank"] < arch_top[arch]["rank"]:
                arch_top[arch] = {"rank": p["rank"], "name": p["name"]}

        # Count all defensive archetypes
        for arch in p.get("all_defensive", []):
            if not arch:
                continue
            if arch not in arch_counts:
                arch_counts[arch] = {1: 0, 2: 0, 3: 0}
                arch_scores[arch] = []
                arch_top[arch] = {"rank": p["rank"], "name": p["name"]}
                arch_type[arch] = "defensive"
            arch_counts[arch][t] += 1
            arch_scores[arch].append(score)
            if p["rank"] < arch_top[arch]["rank"]:
                arch_top[arch] = {"rank": p["rank"], "name": p["name"]}

    # Depth table rows
    depth_rows = []
    for arch in sorted(arch_counts.keys(), key=lambda a: sum(arch_counts[a].values()), reverse=True):
        c = arch_counts[arch]
        total = sum(c.values())
        lottery = c[1]
        late1 = c[2]
        second = c[3]
        scores = arch_scores[arch]
        avg_score = round(sum(scores) / len(scores), 1) if scores else 0

        if lottery == 0 and total <= 2:
            signal = "Very Scarce"
        elif lottery == 0 and total <= 5:
            signal = "Scarce"
        elif total <= 10:
            signal = "Moderate"
        else:
            signal = "Deep"
        if lottery > 0 and second == 0:
            signal += " (top-heavy)"

        top = arch_top[arch]
        depth_rows.append({
            "archetype": arch,
            "arch_side": arch_type.get(arch, "offensive"),
            "total": total,
            "lottery": lottery,
            "late_1st": late1,
            "second_rd": second,
            "avg_score": avg_score,
            "top_prospect_rank": top["rank"],
            "top_prospect_name": top["name"],
            "depth_signal": signal,
            "scores": scores,
            "tier_counts": {str(k): v for k, v in c.items()},
        })

    # Positional gaps — count across all archetypes
    gap_data = {}
    for p in top200:
        for arch in p.get("all_offensive", []) + p.get("all_defensive", []):
            if not arch:
                continue
            key = f"{p['pos']}|{arch}"
            if key not in gap_data:
                gap_data[key] = {"pos": p["pos"], "archetype": arch,
                                 "total": 0, "lottery": 0, "best_rank": 9999}
            gap_data[key]["total"] += 1
            if p["tier"] == 1:
                gap_data[key]["lottery"] += 1
            gap_data[key]["best_rank"] = min(gap_data[key]["best_rank"], p["rank"])

    gap_rows = [v for v in gap_data.values() if v["total"] <= 3]
    gap_rows.sort(key=lambda x: x["total"])

    # Conference archetype production — count all archetypes
    conf_arch = {}
    for p in top200:
        conf = p.get("conference", "Other")
        if conf not in conf_arch:
            conf_arch[conf] = {}
        for arch in p.get("all_offensive", []):
            if arch:
                conf_arch[conf][arch] = conf_arch[conf].get(arch, 0) + 1

    conf_rows = []
    for conf in sorted(conf_arch.keys()):
        dist = conf_arch[conf]
        total_players = len([p for p in top200 if p.get("conference") == conf])
        top3 = sorted(dist.items(), key=lambda x: x[1], reverse=True)[:3]
        top_player = min([p for p in top200 if p.get("conference") == conf], key=lambda x: x["rank"])
        conf_rows.append({
            "conference": conf,
            "prospects": total_players,
            "top_archetypes": ", ".join(f"{a} ({n})" for a, n in top3),
            "top_prospect_rank": top_player["rank"],
            "top_prospect_name": top_player["name"],
        })

    # Browse table (all 200 players with all archetype info)
    browse_rows = []
    for p in top200:
        browse_rows.append({
            "rank": p["rank"],
            "name": p["name"],
            "pos": p["pos"],
            "school": p["school"],
            "conference": p.get("conference", ""),
            "year": p["year"],
            "height": p["height"],
            "tier": p["tier"],
            "draft_score": round(p.get("draft_score", 0), 1),
            "archetype": p["archetype"],
            "defensive_archetype": p.get("defensive_archetype", ""),
            "all_offensive": p.get("all_offensive", []),
            "all_defensive": p.get("all_defensive", []),
            "ppg": p["stats"].get("PPG"),
            "rpg": p["stats"].get("RPG"),
            "apg": p["stats"].get("APG"),
        })

    scarcity = {
        "depth": depth_rows,
        "gaps": gap_rows,
        "conferences": conf_rows,
        "players": browse_rows,
    }

    scarcity_file = Path(__file__).parent / "scarcity.json"
    with open(scarcity_file, "w", encoding="utf-8") as f:
        json.dump(scarcity, f, indent=2, ensure_ascii=False)
    print(f"Scarcity data saved to scarcity.json ({len(depth_rows)} archetypes, {len(browse_rows)} players)")


if __name__ == "__main__":
    main()
