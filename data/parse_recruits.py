#!/usr/bin/env python3
"""Parse recruits/raw/<year>.tsv → recruits/recruits_<year>.json (top-50 247Sports composite)."""
import json, sys

from core.config import RECRUITS_DIR as OUT, RECRUITS_RAW_DIR as RAW
from core.names import normalize_name as norm

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

def main():
    for tsv in sorted(RAW.glob("*.tsv")):
        y = int(tsv.stem)
        lines = [ln.rstrip() for ln in tsv.read_text(encoding="utf-8").splitlines() if ln.strip()]
        recruits = []
        for ln in lines[1:]:  # skip header
            cells = ln.split("\t")
            if len(cells) < 4:
                continue
            try:
                rank = int(cells[0].strip())
            except ValueError:
                continue
            recruits.append({
                "name": cells[1].strip(),
                "norm_name": norm(cells[1].strip()),
                "espn_rank": rank,
                "position": cells[2].strip(),
                "college_commit": cells[3].strip(),
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


if __name__ == "__main__":
    main()
