#!/usr/bin/env python3
"""
Find what curated top-100 NBA players had in common in their college season.

Reads stars_list.json (a curated ranking with archetype + position + tier),
matches each name against our scraped NCAA seasons (history + current), and
reports:
  - Who we have college data for
  - Aggregate college stat profile by NBA tier (T1 / T2 / T3+)
  - Same breakdown by NBA position group (G / wings / bigs)
  - Same by archetype (Floor General, Sharpshooter, etc.)
  - Who's missing (needs older-year scrape or no-NCAA route)
"""
import json, re, sys, unicodedata, statistics
from pathlib import Path
sys.stdout.reconfigure(encoding="utf-8")

ROOT = Path(__file__).parent
H = ROOT / "history"

def norm(name):
    name = unicodedata.normalize("NFKD", name or "")
    name = "".join(c for c in name if not unicodedata.combining(c))
    return re.sub(r"\s+", " ", re.sub(r"[^\w\s]", "", re.sub(r"\s+(jr|sr|ii|iii|iv|v)\.?$", "", name.lower().strip())))

# Load all our NCAA player records across years
all_records: dict[str, dict] = {}  # norm_name -> player (with _year added)
for f in [ROOT / "players.json"] + sorted(H.glob("players_*.json")):
    d = json.load(open(f, encoding="utf-8"))
    y = 2026 if f.name == "players.json" else int(re.search(r"(\d{4})", f.name).group(1))
    for p in d["players"]:
        p["_year"] = y
        key = norm(p["name"])
        # Prefer earliest year (their original draft eligibility season)
        if key not in all_records or y < all_records[key]["_year"]:
            all_records[key] = p

stars = json.load(open(ROOT / "stars_list.json", encoding="utf-8"))

# Bucket each star
found, missing_no_ncaa, missing_pre2020, missing_other = [], [], [], []
for s in stars:
    if s.get("no_ncaa"):
        missing_no_ncaa.append(s)
        continue
    rec = all_records.get(norm(s["name"]))
    if rec:
        found.append({**s, "rec": rec})
    elif s.get("year_ncaa") and s["year_ncaa"] < 2020:
        missing_pre2020.append(s)
    else:
        missing_other.append(s)

print(f"Of {len(stars)} curated NBA stars:")
print(f"  ✓ found in our scrape:    {len(found)}")
print(f"  ✗ no NCAA (Europe/HS):   {len(missing_no_ncaa)}  e.g. {[s['name'] for s in missing_no_ncaa[:3]]}")
print(f"  ✗ pre-2020 college:      {len(missing_pre2020)}  e.g. {[s['name'] for s in missing_pre2020[:3]]}")
print(f"  ? other missing:         {len(missing_other)}  e.g. {[s['name'] for s in missing_other[:5]]}")

def collect(filt):
    rows = []
    for f in found:
        if not filt(f): continue
        p = f["rec"]
        s, a = p["stats"], p["advanced"]
        c = p.get("combine") or {}
        rows.append({
            "name": p["name"], "arch": f["arch"], "tier": f["tier"], "pos_nba": f["pos_nba"],
            "PPG": s.get("PPG"), "APG": s.get("APG"), "RPG": s.get("RPG"),
            "SPG": s.get("SPG"), "BPG": s.get("BPG"), "MPG": s.get("MPG"),
            "TS": a.get("TS%"), "USG": a.get("USG%"), "BPM": a.get("BPM"),
            "DBPM": a.get("DBPM"), "PER": a.get("PER"), "WS40": a.get("WS/40"),
            "AST_pct": a.get("AST%"), "TOV_pct": a.get("TOV%"), "FT_pct": s.get("FT%"),
            "TP_pct": s.get("3P%"), "TPA": s.get("3PA"),
            "year_class": p.get("year"), "height": p.get("height"),
            "wingspan_in": c.get("wingspan_in"), "hand_length_in": c.get("hand_length_in"),
        })
    return rows

def mean(rows, k):
    vals = [r[k] for r in rows if r[k] is not None]
    return statistics.mean(vals) if vals else None

def summarize(rows, label):
    if not rows: return
    print(f"\n  {label}  (n={len(rows)})")
    for k in ["PPG","APG","RPG","SPG","BPG","TS","USG","BPM","DBPM","PER","WS40","FT_pct","TP_pct","TPA"]:
        m = mean(rows, k)
        if m is not None:
            print(f"     {k:<8} = {m:>6.2f}")

# Position group helpers
GUARDS = {"PG","SG"}
WINGS = {"SF"}
BIGS  = {"PF","C"}

print("\n=== PROFILE BY NBA POSITION ===")
summarize(collect(lambda f: f["pos_nba"] in GUARDS), "Guards (PG/SG)")
summarize(collect(lambda f: f["pos_nba"] in WINGS), "Wings (SF)")
summarize(collect(lambda f: f["pos_nba"] in BIGS),  "Bigs (PF/C)")

print("\n=== PROFILE BY NBA TIER ===")
summarize(collect(lambda f: f["tier"] == 1), "Tier 1 (top 7 players)")
summarize(collect(lambda f: f["tier"] == 2), "Tier 2 (All-Stars / All-NBA)")
summarize(collect(lambda f: f["tier"] == 3), "Tier 3 (Quality starters)")

print("\n=== INDIVIDUAL PROFILES FOUND ===")
print(f"{'NBA #':<5} {'Tier':<4} {'Pos':<3} {'Name':<25} {'PPG':>5} {'APG':>5} {'BPM':>5} {'TS':>5} {'USG':>5} {'WS40':>6}  arch")
for f in sorted(found, key=lambda x: x["rank"]):
    p = f["rec"]; s, a = p["stats"], p["advanced"]
    print(f"#{f['rank']:<4} T{f['tier']:<3} {f['pos_nba']:<3} {p['name']:<25} "
          f"{s.get('PPG',0) or 0:>5.1f} {s.get('APG',0) or 0:>5.1f} "
          f"{a.get('BPM',0) or 0:>5.1f} {a.get('TS%',0) or 0:>5.1f} "
          f"{a.get('USG%',0) or 0:>5.1f} {a.get('WS/40',0) or 0:>6.3f}  {f['arch']}")
