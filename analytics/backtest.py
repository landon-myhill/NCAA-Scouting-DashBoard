#!/usr/bin/env python3
"""
analytics.backtest — shared foundation for NBA-outcome backtesting & formula tuning
-----------------------------------------------------------------------------
Everything here serves ONE goal: measure how well a college-stats score
predicts ACTUAL NBA career value (not draft position).

Core pieces:
  - load_matched(years)      -> list[MatchedPlayer] with college record + NBA outcome
  - blended_nba_value(rows)  -> attaches a 0..1 'target' (WS+VORP+tier composite)
  - spearman(xs, ys)         -> rank correlation
  - evaluate(score_fn, ...)  -> per-year + pooled correlation of a scoring fn vs target

Evaluable population = DRAFTED players we can match to a college season.
(We only have NBA outcome data for drafted players; undrafted-gem detection
would need separate scraping — see TODO at bottom.)

Mature-career years only: 2020-2023. 2024-2025 careers are too young to be
ground truth (no stars have emerged yet).
"""

import sys

from core import HISTORY_DIR, load_json
from core.config import MATURE_DRAFT_YEARS
from core.names import normalize_name as norm, match_player

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

# Classes with mature-enough NBA careers to treat as ground truth.
MATURE_YEARS = list(MATURE_DRAFT_YEARS)

# Ordinal value of each career tier (the human-graded NBA outcome).
TIER_VALUE = {"no_nba": 0, "bench": 1, "rotation": 2, "starter": 3, "star": 4}

# name matching lives in core.names (normalize_name as `norm`, match_player).
_match = match_player


def load_matched(years=MATURE_YEARS, include_undrafted=False):
    """
    Return a list of dicts, one per player matched to a college season:
      { year, pick, player, college_record (full dict), ws, vorp, value,
        tier_val, tier }
    college_record is the raw NCAA player dict — feed it to any scoring function.

    include_undrafted=True adds top-150 board players who were never drafted
    (datasets/history/undrafted_results_*.json) with their real outcomes —
    mostly no_nba, plus the Jay Huff / Austin Reaves types who made it anyway.
    This is the fix for the drafted-only selection bias; pick is None for them.
    """
    rows = []
    for y in years:
        pf = HISTORY_DIR / f"players_{y}.json"
        df = HISTORY_DIR / f"draft_results_{y}.json"
        if not pf.exists() or not df.exists():
            continue
        players = load_json(pf)["players"]
        picks = load_json(df)["picks"]
        by_norm = {norm(p["name"]): p for p in players}
        by_school = {}
        for p in players:
            by_school.setdefault(p.get("school", ""), []).append(p)
        seen_ids = set()  # guard vs name-variant double counts (Bones/Nah'Shon Hyland)
        for pick in picks:
            rec = _match(pick, by_norm, by_school)
            if rec is None:
                continue
            seen_ids.add(rec.get("id"))
            car = pick.get("career", {})
            rows.append({
                "year": y,
                "pick": pick["pick_overall"],
                "player": pick["player"],
                "college_record": rec,
                "ws": car.get("WS"),
                "vorp": car.get("VORP"),
                "value": pick.get("nba_value"),  # position-relative box-score value
                "tier": pick["career_tier"],
                "tier_val": TIER_VALUE.get(pick["career_tier"], 0),
            })
        uf = HISTORY_DIR / f"undrafted_results_{y}.json"
        if include_undrafted and uf.exists():
            for r in load_json(uf)["players"]:
                # Class-eligibility rule: players who RETURNED to college are
                # not part of this draft class (flagged by make_class_boards).
                if r.get("returned"):
                    continue
                rec = _match({"player": r["player"], "college": r.get("college", "")},
                             by_norm, by_school)
                if rec is None or rec.get("id") in seen_ids:
                    continue
                seen_ids.add(rec.get("id"))
                car = r.get("career") or {}
                tier = r.get("career_tier", "no_nba")
                rows.append({
                    "year": y,
                    "pick": None,
                    "player": r["player"],
                    "college_record": rec,
                    "ws": car.get("WS"),
                    "vorp": car.get("VORP"),
                    "value": r.get("nba_value"),
                    "tier": tier,
                    "tier_val": TIER_VALUE.get(tier, 0),
                })
    return rows


def attach_value_target(rows):
    """Target = position-relative NBA career value (analytics.value), the
    box-score grade that replaced the WS/VORP blend. Falls back to the legacy
    blended target only if the files haven't been rescored yet."""
    if all(r.get("value") is None for r in rows):
        return attach_blended_target(rows)
    for r in rows:
        r["target"] = r.get("value")
    return rows


# ── target: blended NBA value ────────────────────────────────────────────────
def _percentile_ranks(values):
    """Map raw values -> [0,1] percentile (average-rank for ties). None -> None."""
    idx = [i for i, v in enumerate(values) if v is not None]
    out = [None] * len(values)
    if not idx:
        return out
    order = sorted(idx, key=lambda i: values[i])
    n = len(order)
    # average-rank handling for ties
    i = 0
    while i < n:
        j = i
        while j + 1 < n and values[order[j + 1]] == values[order[i]]:
            j += 1
        avg_rank = (i + j) / 2.0
        pct = avg_rank / (n - 1) if n > 1 else 0.5
        for k in range(i, j + 1):
            out[order[k]] = pct
        i = j + 1
    return out


def attach_blended_target(rows, w_ws=1.0, w_vorp=1.0, w_tier=1.0):
    """
    Attach row['target'] in [0,1] = weighted mean of the percentile ranks of
    (WS, VORP, tier). Percentiles are computed POOLED across all rows passed in,
    so call this once on the full evaluable set. Components that are None for a
    player are dropped from that player's mean (weights renormalized).
    """
    ws_p = _percentile_ranks([r["ws"] for r in rows])
    vorp_p = _percentile_ranks([r["vorp"] for r in rows])
    tier_p = _percentile_ranks([r["tier_val"] for r in rows])
    for i, r in enumerate(rows):
        parts = []
        if ws_p[i] is not None:
            parts.append((w_ws, ws_p[i]))
        if vorp_p[i] is not None:
            parts.append((w_vorp, vorp_p[i]))
        if tier_p[i] is not None:
            parts.append((w_tier, tier_p[i]))
        wsum = sum(w for w, _ in parts)
        r["target"] = sum(w * v for w, v in parts) / wsum if wsum else None
    return rows


# ── correlation ──────────────────────────────────────────────────────────────
def spearman(xs, ys):
    pairs = [(x, y) for x, y in zip(xs, ys) if x is not None and y is not None]
    n = len(pairs)
    if n < 3:
        return None
    xr = _rank([p[0] for p in pairs])
    yr = _rank([p[1] for p in pairs])
    d2 = sum((a - b) ** 2 for a, b in zip(xr, yr))
    return 1 - 6 * d2 / (n * (n * n - 1))


def _rank(vals):
    order = sorted(range(len(vals)), key=lambda i: vals[i])
    r = [0.0] * len(vals)
    i = 0
    while i < len(order):
        j = i
        while j + 1 < len(order) and vals[order[j + 1]] == vals[order[i]]:
            j += 1
        avg = (i + j) / 2.0 + 1
        for k in range(i, j + 1):
            r[order[k]] = avg
        i = j + 1
    return r


# ── evaluation ───────────────────────────────────────────────────────────────
def evaluate(score_fn, rows, label="score"):
    """
    Score every row with score_fn(college_record) and report Spearman vs target,
    per-year and pooled. Returns dict with 'pooled' and 'per_year'.
    """
    for r in rows:
        r[label] = score_fn(r["college_record"])
    per_year = {}
    for y in sorted({r["year"] for r in rows}):
        yr = [r for r in rows if r["year"] == y]
        per_year[y] = spearman([r[label] for r in yr], [r["target"] for r in yr])
    pooled = spearman([r[label] for r in rows], [r["target"] for r in rows])
    return {"pooled": pooled, "per_year": per_year, "n": len(rows)}


# TODO(undrafted): we only see NBA outcomes for drafted players. To reward the
# formula for catching undrafted contributors (and not just ranking the drafted
# pool), scrape NBA careers for the top ~150 college players/year regardless of
# draft status and fold them in as additional rows with their real outcome.

if __name__ == "__main__":
    rows = load_matched()
    attach_value_target(rows)
    from model.archetypes import draft_score
    res = evaluate(lambda rec: draft_score(rec), rows)
    print(f"Evaluable matched players (2020-2023): {res['n']}")
    print(f"\nCurrent formula vs BLENDED NBA VALUE:")
    print(f"  Pooled Spearman: {res['pooled']:+.3f}")
    for y, rho in res["per_year"].items():
        print(f"    {y}: {rho:+.3f}" if rho is not None else f"    {y}: n/a")
