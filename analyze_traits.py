#!/usr/bin/env python3
"""
Trait Discovery: What separates NBA Stars from Busts in their college season?
-----------------------------------------------------------------------------
For every available (NCAA season, NBA draft) pair, this script:

  1. Matches each drafted player back to their NCAA stats line
  2. Groups them by career_tier (star, starter, rotation, bench, no_nba)
  3. Reports mean & median for each college stat, per tier
  4. Computes a "signal strength" for each stat — how cleanly does it
     separate star/starter from bench/no_nba? (large positive number =
     strong predictor of NBA success)

The signal-strength column is what the formula rework will use to decide
which stats deserve more weight, and which we're currently over-rewarding.

Usage:
    python analyze_traits.py                # all available years
    python analyze_traits.py 2020 2021      # subset
"""

import json
import re
import statistics
import sys
import unicodedata
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

HISTORY_DIR = Path(__file__).parent / "history"

TIERS_ORDER = ["star", "starter", "rotation", "bench", "no_nba"]
# Tiers we consider "good NBA outcome" vs "bad" for signal calculation
GOOD = {"star", "starter"}
BAD = {"bench", "no_nba"}


def _norm(name):
    name = unicodedata.normalize("NFKD", name or "")
    name = "".join(c for c in name if not unicodedata.combining(c))
    name = name.lower().strip()
    name = re.sub(r"\s+(jr|sr|ii|iii|iv|v)\.?$", "", name)
    name = re.sub(r"[^\w\s]", "", name)
    name = re.sub(r"\s+", " ", name)
    return name


def _height_inches(h):
    if not h: return None
    m = re.match(r"(\d+)'(\d+)", h)
    if not m: return None
    return int(m.group(1)) * 12 + int(m.group(2))


_CLASS_NUM = {"Freshman": 1, "Sophomore": 2, "Junior": 3,
              "Senior": 4, "Graduate": 5, "5th Year": 5}


def _flatten_player(p, career_tier):
    """Turn a player record into a flat dict for stat aggregation."""
    s, a = p.get("stats", {}), p.get("advanced", {})
    return {
        "tier": career_tier,
        "name": p["name"],
        "pos": p.get("pos", ""),
        "year_class": _CLASS_NUM.get(p.get("year", ""), None),
        "height_in": _height_inches(p.get("height", "")),
        "PPG": s.get("PPG"), "RPG": s.get("RPG"), "APG": s.get("APG"),
        "SPG": s.get("SPG"), "BPG": s.get("BPG"),
        "FG%": s.get("FG%"), "3P%": s.get("3P%"), "FT%": s.get("FT%"),
        "MPG": s.get("MPG"), "TOV": s.get("TOV"), "FTA": s.get("FTA"),
        "3PA": s.get("3PA"), "DREB": s.get("DREB"), "OREB": s.get("OREB"),
        "PER": a.get("PER"), "TS%": a.get("TS%"), "eFG%": a.get("eFG%"),
        "USG%": a.get("USG%"), "BPM": a.get("BPM"),
        "OBPM": a.get("OBPM"), "DBPM": a.get("DBPM"),
        "WS": a.get("Win Shares"), "WS/40": a.get("WS/40"),
        "DWS": a.get("DWS"), "OWS": a.get("OWS"),
        "AST%": a.get("AST%"), "TOV%": a.get("TOV%"),
        # Useful derived: per-36 stats, neutralizes minutes
        "PPG36": (s.get("PPG") or 0) * 36 / max(s.get("MPG") or 1, 15),
        "RPG36": (s.get("RPG") or 0) * 36 / max(s.get("MPG") or 1, 15),
        "draft_score_ours": p.get("draft_score"),
    }


def gather(years):
    rows = []
    unmatched_count = 0
    for y in years:
        pf = HISTORY_DIR / f"players_{y}.json"
        df = HISTORY_DIR / f"draft_results_{y}.json"
        if not (pf.exists() and df.exists()):
            print(f"  skip {y}: missing data")
            continue
        players = json.load(open(pf, encoding="utf-8"))["players"]
        picks = json.load(open(df, encoding="utf-8"))["picks"]
        by_norm = {_norm(p["name"]): p for p in players}
        for pick in picks:
            n = _norm(pick["player"])
            ncaa = by_norm.get(n)
            if not ncaa:
                # Try last-name fallback
                parts = n.split()
                if len(parts) >= 2:
                    for k, v in by_norm.items():
                        kp = k.split()
                        if len(kp) >= 2 and kp[-1] == parts[-1] and kp[0][0] == parts[0][0]:
                            ncaa = v
                            break
            if not ncaa:
                unmatched_count += 1
                continue
            row = _flatten_player(ncaa, pick["career_tier"])
            row["draft_year"] = y
            row["pick"] = pick["pick_overall"]
            rows.append(row)
    return rows, unmatched_count


def _mean_or_none(vals):
    vals = [v for v in vals if v is not None]
    return statistics.mean(vals) if vals else None


def _median_or_none(vals):
    vals = [v for v in vals if v is not None]
    return statistics.median(vals) if vals else None


def _stdev_or_none(vals):
    vals = [v for v in vals if v is not None]
    return statistics.stdev(vals) if len(vals) >= 2 else None


STATS_TO_REPORT = [
    "year_class", "height_in",
    "PPG", "PPG36", "RPG", "RPG36", "APG", "SPG", "BPG",
    "FG%", "3P%", "FT%", "3PA", "MPG", "TOV",
    "PER", "TS%", "eFG%", "USG%", "BPM", "OBPM", "DBPM",
    "WS", "WS/40", "AST%", "TOV%",
    "draft_score_ours",
]


def report(rows, label="ALL YEARS"):
    tiers = {t: [r for r in rows if r["tier"] == t] for t in TIERS_ORDER}
    counts = {t: len(tiers[t]) for t in TIERS_ORDER}
    n_good = sum(counts[t] for t in GOOD)
    n_bad = sum(counts[t] for t in BAD)

    print(f"\n{'='*100}")
    print(f"TRAIT ANALYSIS — {label}")
    print(f"{'='*100}")
    print(f"Sample sizes:  " + "  ".join(f"{t}={counts[t]}" for t in TIERS_ORDER))
    print(f"               good (star+starter)={n_good}   bad (bench+no_nba)={n_bad}")

    # Column header
    print(f"\n{'Stat':<18}  " + "  ".join(f"{t[:8]:>8}" for t in TIERS_ORDER) +
          f"  {'good-bad':>9}  {'signal':>7}")
    print("-" * 100)

    signals = []
    for stat in STATS_TO_REPORT:
        means = {t: _mean_or_none([r[stat] for r in tiers[t]]) for t in TIERS_ORDER}
        good_vals = [r[stat] for r in rows if r["tier"] in GOOD]
        bad_vals = [r[stat] for r in rows if r["tier"] in BAD]
        gmean = _mean_or_none(good_vals)
        bmean = _mean_or_none(bad_vals)
        if gmean is None or bmean is None:
            continue
        diff = gmean - bmean
        # Signal strength = (mean_good - mean_bad) / pooled_stdev. Like Cohen's d.
        pool = [v for v in good_vals + bad_vals if v is not None]
        sd = _stdev_or_none(pool)
        signal = (diff / sd) if sd and sd > 0 else 0
        signals.append((stat, signal))

        cells = []
        for t in TIERS_ORDER:
            v = means[t]
            cells.append(f"{v:>8.2f}" if v is not None else f"{'—':>8}")
        print(f"{stat:<18}  " + "  ".join(cells) + f"  {diff:>+9.2f}  {signal:>+7.2f}")

    # Sort by absolute signal strength
    signals.sort(key=lambda x: abs(x[1]), reverse=True)
    print(f"\nStrongest predictors of NBA success (|signal| = (mean_good - mean_bad) / stdev):")
    for stat, sig in signals[:15]:
        marker = "  GOOD predictor" if sig > 0 else "  REVERSE (high = worse outcome)"
        print(f"  {stat:<18}  signal = {sig:+.3f}{marker if abs(sig) > 0.3 else ''}")


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    if args:
        years = [int(a) for a in args]
    else:
        years = sorted({
            int(re.search(r"(\d{4})", f.stem).group(1))
            for f in HISTORY_DIR.glob("players_*.json")
            if (HISTORY_DIR / f.name.replace("players", "draft_results")).exists()
        })

    if not years:
        print("No paired (players, draft_results) files found in history/")
        return

    print(f"Years analyzed: {years}")
    rows, unmatched = gather(years)
    print(f"Matched {len(rows)} drafted players to NCAA records ({unmatched} unmatched, mostly internationals).")

    report(rows, label=f"{years[0]}-{years[-1]}")


if __name__ == "__main__":
    main()
