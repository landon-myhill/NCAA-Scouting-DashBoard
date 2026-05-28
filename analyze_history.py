#!/usr/bin/env python3
"""
Historical Backtest: Formula vs Actual NBA Draft Outcomes
----------------------------------------------------------
For each year with both history/players_<year>.json and
history/draft_results_<year>.json, this script:

  1. Matches NBA draftees back to NCAA player records by name + school
  2. Compares formula rank to actual draft position
  3. Computes tier-hit-rates AND Spearman rank correlation
  4. Identifies STEALS: players the formula ranked highly but were
     drafted late (or undrafted) — measured against actual NBA outcomes
  5. Identifies REACHES: players drafted early that the formula didn't see

Usage:
    python analyze_history.py                # all available years
    python analyze_history.py 2024 2025      # subset
"""

import json
import re
import sys
import unicodedata
from pathlib import Path

# Windows console defaults to cp1252; force UTF-8 so European names print
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

HISTORY_DIR = Path(__file__).parent / "history"


def _norm(name: str) -> str:
    name = unicodedata.normalize("NFKD", name or "")
    name = "".join(c for c in name if not unicodedata.combining(c))
    name = name.lower().strip()
    name = re.sub(r"\s+(jr|sr|ii|iii|iv|v)\.?$", "", name)
    name = re.sub(r"[^\w\s]", "", name)
    name = re.sub(r"\s+", " ", name)
    return name


def _match_pick_to_player(pick, players_by_norm: dict, players_by_school: dict) -> dict | None:
    """Return the matching NCAA player record, or None."""
    n = _norm(pick["player"])
    if n in players_by_norm:
        return players_by_norm[n]
    # Try school-scoped match (handles two same-named guys at different schools)
    school = pick.get("college", "").strip()
    if school:
        candidates = players_by_school.get(school, [])
        for p in candidates:
            if _norm(p["name"]).endswith(n.split()[-1]):
                return p
    # First initial + last name fallback
    parts = n.split()
    if len(parts) >= 2:
        key = f"{parts[0][0]} {parts[-1]}"
        for full, p in players_by_norm.items():
            full_parts = full.split()
            if len(full_parts) >= 2 and f"{full_parts[0][0]} {full_parts[-1]}" == key:
                return p
    return None


def analyze_year(year: int) -> dict:
    """Run the full backtest for one season + draft."""
    players_file = HISTORY_DIR / f"players_{year}.json"
    draft_file = HISTORY_DIR / f"draft_results_{year}.json"
    if not players_file.exists():
        return {"year": year, "error": f"missing {players_file.name}"}
    if not draft_file.exists():
        return {"year": year, "error": f"missing {draft_file.name}"}

    players_raw = json.loads(players_file.read_text(encoding="utf-8"))
    draft_raw = json.loads(draft_file.read_text(encoding="utf-8"))
    players = players_raw["players"]
    picks = draft_raw["picks"]

    players_by_norm = {_norm(p["name"]): p for p in players}
    players_by_school: dict[str, list] = {}
    for p in players:
        players_by_school.setdefault(p["school"], []).append(p)

    # Match each pick to NCAA record
    matched, unmatched = [], []
    for pick in picks:
        ncaa = _match_pick_to_player(pick, players_by_norm, players_by_school)
        if ncaa:
            matched.append({
                "pick": pick["pick_overall"],
                "player": pick["player"],
                "college": pick.get("college", ""),
                "career_tier": pick["career_tier"],
                "career_WS": pick["career"].get("WS"),
                "career_VORP": pick["career"].get("VORP"),
                "our_rank": ncaa["rank"],
                "our_score": ncaa["draft_score"],
                "delta": pick["pick_overall"] - ncaa["rank"],  # +N = we ranked higher
                "year_class": ncaa.get("year", ""),
                "pos": ncaa.get("pos", ""),
                "school": ncaa.get("school", ""),
            })
        else:
            unmatched.append(pick["player"])

    # ── Tier-based metrics ────────────────────────────────────────────────
    actual_top14 = {p["player"] for p in picks if p["pick_overall"] <= 14}
    actual_top30 = {p["player"] for p in picks if p["pick_overall"] <= 30}
    actual_top60 = {p["player"] for p in picks}
    our_top14 = {p["name"] for p in players[:14]}
    our_top30 = {p["name"] for p in players[:30]}
    our_top60 = {p["name"] for p in players[:60]}

    # Hits via normalized names
    actual_top14_n = {_norm(p["player"]) for p in picks if p["pick_overall"] <= 14}
    actual_top30_n = {_norm(p["player"]) for p in picks if p["pick_overall"] <= 30}
    actual_top60_n = {_norm(p["player"]) for p in picks}
    our_top14_n = {_norm(p["name"]) for p in players[:14]}
    our_top30_n = {_norm(p["name"]) for p in players[:30]}
    our_top60_n = {_norm(p["name"]) for p in players[:60]}

    def overlap(a, b):
        return len(a & b)

    # ── Rank correlation (Spearman on the matched pairs) ─────────────────
    def spearman(matched_pairs):
        # Rank both arrays, compute Pearson on ranks
        if len(matched_pairs) < 3:
            return None
        ours = sorted(matched_pairs, key=lambda m: m["our_rank"])
        their_ranks = {id(m): i + 1 for i, m in enumerate(sorted(matched_pairs, key=lambda m: m["pick"]))}
        n = len(matched_pairs)
        # Use rank arrays
        our_ranks = {id(m): i + 1 for i, m in enumerate(ours)}
        d2 = sum((our_ranks[id(m)] - their_ranks[id(m)]) ** 2 for m in matched_pairs)
        return 1 - (6 * d2) / (n * (n * n - 1))

    rho = spearman(matched)

    # ── Steals: we ranked high but drafted late (or rotation+ career) ────
    # Definition: our_rank ≤ 30 AND actual_pick > 40, with career ≥ rotation
    steals = [m for m in matched
              if m["our_rank"] <= 30 and m["pick"] >= 40
              and m["career_tier"] in ("rotation", "starter", "star")]
    # Also: undrafted-but-good would be cases where a player in our top 30
    # doesn't appear in the picks list at all and was an NBA contributor.
    # We can't measure that here without separate undrafted-NBA data.

    # ── Reaches: drafted early but we ranked low (or busted) ─────────────
    reaches = [m for m in matched
               if m["pick"] <= 30 and m["our_rank"] > 60
               and m["career_tier"] in ("bench", "no_nba")]

    # ── Misses: drafted top 60, didn't appear in our top 100 ─────────────
    missed = [m for m in matched if m["pick"] <= 60 and m["our_rank"] > 100]

    return {
        "year": year,
        "season": players_raw.get("season"),
        "matched": len(matched),
        "unmatched": unmatched,
        "actual_drafted": len(picks),
        "total_players": len(players),
        "tier_hit_rate": {
            "top14": (overlap(our_top14_n, actual_top14_n), len(actual_top14_n)),
            "top30": (overlap(our_top30_n, actual_top30_n), len(actual_top30_n)),
            "top60": (overlap(our_top60_n, actual_top60_n), len(actual_top60_n)),
        },
        "rank_correlation_spearman": rho,
        "matched_picks": sorted(matched, key=lambda m: m["pick"]),
        "steals": sorted(steals, key=lambda m: m["pick"] - m["our_rank"], reverse=True),
        "reaches": sorted(reaches, key=lambda m: m["our_rank"] - m["pick"], reverse=True),
        "missed_entirely": sorted(missed, key=lambda m: m["pick"]),
    }


def print_year_report(r: dict):
    print(f"\n{'='*70}")
    print(f"YEAR {r['year']}  (season {r.get('season')})")
    print(f"{'='*70}")
    if r.get("error"):
        print(f"  ERROR: {r['error']}")
        return
    print(f"Matched {r['matched']}/{r['actual_drafted']} drafted players to NCAA records")
    if r["unmatched"]:
        print(f"Unmatched: {', '.join(r['unmatched'][:8])}{'...' if len(r['unmatched'])>8 else ''}")

    h = r["tier_hit_rate"]
    print(f"\nTier hit rate:")
    print(f"  Top 14 (lottery): {h['top14'][0]}/{h['top14'][1]}  ({100*h['top14'][0]/max(h['top14'][1],1):.0f}%)")
    print(f"  Top 30 (1st rd):  {h['top30'][0]}/{h['top30'][1]}  ({100*h['top30'][0]/max(h['top30'][1],1):.0f}%)")
    print(f"  Top 60 (both rds):{h['top60'][0]}/{h['top60'][1]}  ({100*h['top60'][0]/max(h['top60'][1],1):.0f}%)")

    rho = r["rank_correlation_spearman"]
    print(f"  Spearman rank correlation: {rho:.3f}" if rho is not None else "  (insufficient matches for correlation)")

    if r["steals"]:
        print(f"\nSTEALS the formula saw  (our top 30, drafted ≥ 40, rotation+ career):")
        for m in r["steals"][:8]:
            print(f"  pick #{m['pick']:>2}  our #{m['our_rank']:>3}  {m['player']:<25} {m['pos']:<3} {m['school']:<20} career={m['career_tier']} WS={m['career_WS']}")

    if r["reaches"]:
        print(f"\nREACHES we saw  (drafted top 30, our rank > 60, didn't pan out):")
        for m in r["reaches"][:8]:
            print(f"  pick #{m['pick']:>2}  our #{m['our_rank']:>3}  {m['player']:<25} {m['pos']:<3} {m['school']:<20} career={m['career_tier']}")

    if r["missed_entirely"]:
        print(f"\nMISSES  (drafted top 60, we had > #100):")
        for m in r["missed_entirely"][:8]:
            print(f"  pick #{m['pick']:>2}  our #{m['our_rank']:>3}  {m['player']:<25} {m['pos']:<3} {m['school']:<20} career={m['career_tier']}")


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    if args:
        years = [int(a) for a in args]
    else:
        years = sorted({
            int(re.search(r"(\d{4})", f.stem).group(1))
            for f in HISTORY_DIR.glob("players_*.json")
            if re.search(r"\d{4}", f.stem)
        })

    if not years:
        print("No history/players_*.json found. Run scrape_history.py first.")
        return

    all_reports = []
    for y in years:
        r = analyze_year(y)
        all_reports.append(r)
        print_year_report(r)

    # ── Aggregate diagnostics ────────────────────────────────────────────
    print(f"\n\n{'='*70}\nCROSS-YEAR DIAGNOSTICS\n{'='*70}")
    valid = [r for r in all_reports if not r.get("error")]
    if not valid:
        return
    # Aggregate matched picks
    all_matched = [m for r in valid for m in r["matched_picks"]]
    if not all_matched:
        return

    # Bias by position
    from collections import defaultdict
    pos_deltas = defaultdict(list)
    for m in all_matched:
        pos_deltas[m["pos"] or "?"].append(m["delta"])
    print("\nFormula bias by position (negative delta = formula ranks LOWER than actual pick):")
    for pos, deltas in sorted(pos_deltas.items()):
        if not deltas: continue
        avg = sum(deltas) / len(deltas)
        print(f"  {pos:>3}: {len(deltas):>3} picks, avg delta = {avg:+6.1f}")

    # Bias by class year
    class_deltas = defaultdict(list)
    for m in all_matched:
        class_deltas[m["year_class"] or "?"].append(m["delta"])
    print("\nFormula bias by class year:")
    for yr, deltas in sorted(class_deltas.items()):
        avg = sum(deltas) / len(deltas) if deltas else 0
        print(f"  {yr:<10}: {len(deltas):>3} picks, avg delta = {avg:+6.1f}")

    # Top steals overall
    all_steals = [m for r in valid for m in r["steals"]]
    all_steals.sort(key=lambda m: m["pick"] - m["our_rank"], reverse=True)
    if all_steals:
        print(f"\nTop steals across all years (by largest pick - our_rank gap):")
        for m in all_steals[:10]:
            gap = m["pick"] - m["our_rank"]
            print(f"  gap=+{gap:>3}  pick #{m['pick']:>2}  our #{m['our_rank']:>3}  {m['player']:<25} career={m['career_tier']}")


if __name__ == "__main__":
    main()
