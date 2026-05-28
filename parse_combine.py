#!/usr/bin/env python3
"""
Parse raw NBA.com combine TSVs into structured JSON.

Reads combine/raw/<year>_anthro.tsv and <year>_athletic.tsv, parses heights
(e.g., "6' 7.5''" -> 79.5 inches), normalizes names, writes one structured
file per year as combine/combine_<year>.json.

Usage:
    python parse_combine.py             # parse every year present in combine/raw/
    python parse_combine.py 2020 2024   # subset
"""

import json
import re
import sys
import unicodedata
from pathlib import Path

RAW_DIR = Path(__file__).parent / "combine" / "raw"
OUT_DIR = Path(__file__).parent / "combine"


def _norm_name(name: str) -> str:
    name = unicodedata.normalize("NFKD", name or "")
    name = "".join(c for c in name if not unicodedata.combining(c))
    name = name.lower().strip()
    name = re.sub(r"\s+(jr|sr|ii|iii|iv|v)\.?$", "", name)
    name = re.sub(r"[^\w\s]", "", name)
    name = re.sub(r"\s+", " ", name)
    return name


def parse_height(s: str):
    """Convert '6' 7.5\\'\\'' or '6'7.5''' to total inches as float."""
    if not s or s.strip() in ("", "-", "--"):
        return None
    m = re.search(r"(\d+)\s*'\s*([\d.]+)", s)
    if not m:
        return None
    return round(int(m.group(1)) * 12 + float(m.group(2)), 2)


def flt(s):
    if not s or s.strip() in ("", "-", "--", "N/A"):
        return None
    try:
        return float(s.strip().rstrip("%"))
    except ValueError:
        return None


def parse_anthro_tsv(path: Path) -> list[dict]:
    """Parse a 2026_anthro.tsv-style file. Returns a list of player dicts."""
    rows: list[dict] = []
    with path.open(encoding="utf-8") as f:
        lines = [ln.rstrip("\n") for ln in f if ln.strip()]
    if not lines:
        return rows
    header = [h.strip() for h in lines[0].split("\t")]

    def col(row, *names):
        for n in names:
            for i, h in enumerate(header):
                if h.upper().startswith(n.upper()):
                    return row[i] if i < len(row) else ""
        return ""

    for line in lines[1:]:
        cells = line.split("\t")
        # Pad short rows
        while len(cells) < len(header):
            cells.append("")
        name = cells[0].strip()
        if not name or name.upper().startswith("PLAYER"):
            continue
        rows.append({
            "name": name,
            "norm_name": _norm_name(name),
            "pos": cells[1].strip(),
            "body_fat_pct": flt(col(cells, "BODY FAT")),
            "hand_length_in": flt(col(cells, "HAND LENGTH")),
            "hand_width_in": flt(col(cells, "HAND WIDTH")),
            "height_no_shoes_in": parse_height(col(cells, "HEIGHT W/O")),
            "height_w_shoes_in": parse_height(col(cells, "HEIGHT W/ SHOES")),
            "standing_reach_in": parse_height(col(cells, "STANDING REACH")),
            "weight_lbs": flt(col(cells, "WEIGHT")),
            "wingspan_in": parse_height(col(cells, "WINGSPAN")),
        })
    return rows


def parse_athletic_tsv(path: Path) -> list[dict]:
    rows: list[dict] = []
    with path.open(encoding="utf-8") as f:
        lines = [ln.rstrip("\n") for ln in f if ln.strip()]
    if not lines:
        return rows
    header = [h.strip() for h in lines[0].split("\t")]

    def col(row, *names):
        for n in names:
            for i, h in enumerate(header):
                if any(k.upper() in h.upper() for k in [n]):
                    return row[i] if i < len(row) else ""
        return ""

    for line in lines[1:]:
        cells = line.split("\t")
        while len(cells) < len(header):
            cells.append("")
        name = cells[0].strip()
        if not name or name.upper().startswith("PLAYER"):
            continue
        rows.append({
            "name": name,
            "norm_name": _norm_name(name),
            "pos": cells[1].strip(),
            "lane_agility_s": flt(col(cells, "Lane Agility")),
            "shuttle_run_s": flt(col(cells, "Shuttle Run")),
            "three_quarter_sprint_s": flt(col(cells, "Three Quarter")),
            "standing_vert_in": flt(col(cells, "Standing Vertical")),
            "max_vert_in": flt(col(cells, "Max Vertical")),
            "max_bench_reps": flt(col(cells, "Max Bench")),
        })
    return rows


def merge_year(year: int) -> dict | None:
    anthro_path = RAW_DIR / f"{year}_anthro.tsv"
    athletic_path = RAW_DIR / f"{year}_athletic.tsv"
    if not anthro_path.exists() and not athletic_path.exists():
        return None
    anthro_rows = parse_anthro_tsv(anthro_path) if anthro_path.exists() else []
    athletic_rows = parse_athletic_tsv(athletic_path) if athletic_path.exists() else []

    # Merge by normalized name
    by_norm: dict[str, dict] = {}
    for a in anthro_rows:
        by_norm[a["norm_name"]] = {**a}
    for a in athletic_rows:
        slot = by_norm.setdefault(a["norm_name"], {
            "name": a["name"], "norm_name": a["norm_name"], "pos": a["pos"],
        })
        for k in ("lane_agility_s", "shuttle_run_s", "three_quarter_sprint_s",
                  "standing_vert_in", "max_vert_in", "max_bench_reps"):
            slot[k] = a.get(k)

    return {
        "year": year,
        "players": sorted(by_norm.values(), key=lambda p: p["name"]),
        "anthro_count": len(anthro_rows),
        "athletic_count": len(athletic_rows),
    }


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    if args:
        years = [int(a) for a in args]
    else:
        years = sorted({
            int(m.group(1))
            for p in RAW_DIR.glob("*_anthro.tsv")
            if (m := re.match(r"(\d{4})_anthro\.tsv", p.name))
        } | {
            int(m.group(1))
            for p in RAW_DIR.glob("*_athletic.tsv")
            if (m := re.match(r"(\d{4})_athletic\.tsv", p.name))
        })

    if not years:
        print("No combine TSVs found in combine/raw/")
        return

    for y in years:
        data = merge_year(y)
        if data is None:
            print(f"  {y}: no files found")
            continue
        out = OUT_DIR / f"combine_{y}.json"
        out.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
        print(f"  {y}: anthro={data['anthro_count']} athletic={data['athletic_count']} "
              f"-> {len(data['players'])} players -> {out.name}")


if __name__ == "__main__":
    main()
