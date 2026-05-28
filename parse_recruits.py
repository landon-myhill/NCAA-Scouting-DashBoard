#!/usr/bin/env python3
"""Parse recruits/raw/<year>.tsv → recruits/recruits_<year>.json (top-50 247Sports composite)."""
import json, re, sys, unicodedata
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

ROOT = Path(__file__).parent
RAW = ROOT / "recruits" / "raw"
OUT = ROOT / "recruits"

def norm(name):
    name = unicodedata.normalize("NFKD", name or "")
    name = "".join(c for c in name if not unicodedata.combining(c))
    name = name.lower().strip()
    name = re.sub(r"\s+(jr|sr|ii|iii|iv|v)\.?$", "", name)
    name = re.sub(r"[^\w\s]", "", name)
    return re.sub(r"\s+", " ", name)

for tsv in sorted(RAW.glob("*.tsv")):
    y = int(tsv.stem)
    lines = [ln.rstrip() for ln in tsv.read_text(encoding="utf-8").splitlines() if ln.strip()]
    recruits = []
    for ln in lines[1:]:  # skip header
        cells = ln.split("\t")
        if len(cells) < 4: continue
        try:
            rank = int(cells[0].strip())
        except ValueError:
            continue
        name = cells[1].strip()
        pos = cells[2].strip()
        college = cells[3].strip()
        recruits.append({
            "name": name,
            "norm_name": norm(name),
            "espn_rank": rank,
            "position": pos,
            "college_commit": college,
            "source": "247sports_composite",
            "hs_class_year": y,
        })
    out = OUT / f"recruits_{y}.json"
    out.write_text(json.dumps({
        "hs_class_year": y,
        "count": len(recruits),
        "recruits": recruits,
    }, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"  {y}: {len(recruits)} recruits → {out.name}")
