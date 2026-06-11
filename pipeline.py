#!/usr/bin/env python3
"""
pipeline.py — the data pipeline DAG, in one runnable place.

Previously the real pipeline was tribal knowledge: the README documented only
scrape -> rerank -> app, but the formula's top feature (recruit rank) and the
size/length features actually arrive through an undocumented chain of scrape ->
parse -> merge steps. This script encodes the whole DAG and its ordering.

STAGES
------
  build   (default, no network) — recompute boards from already-scraped data:
            merge_recruits -> merge_combine -> rerank -> rerank_history -> predict
          Run this after editing the formula.

  scrape  (network, slow ~15 min) — full refresh from the web, then build:
            scrape -> scrape_history -> scrape_draft -> scrape_draft_results
            -> scrape_recruits -> parse_recruits -> parse_combine -> [build]

  test    — run the pytest suite.

Usage:
    python pipeline.py            # build (local recompute)
    python pipeline.py build
    python pipeline.py scrape     # full network refresh + build
    python pipeline.py test
    python pipeline.py --plan     # print the DAG and exit
"""

import subprocess
import sys

# (module, human description), run as `python -m <module>` from the repo root.
ACQUIRE = [
    ("data.scrape", "Scrape current-season D1 box scores -> players.json"),
    ("data.scrape_history", "Scrape prior seasons -> history/players_<year>.json"),
    ("data.scrape_draft", "Scrape declared draft entrants -> draft_eligible.json"),
    ("data.scrape_draft_results", "Scrape NBA draft results + careers -> history/draft_results_*"),
    ("data.scrape_recruits", "Scrape HS recruit rankings -> recruits/recruits_*.json"),
    ("data.parse_recruits", "Parse recruit raw files -> recruits/recruits_*.json"),
    ("data.parse_combine", "Parse combine raw files -> combine/combine_*.json"),
    ("data.scrape_intl", "Scrape intl stats for curated-board names -> intl/intl_*.json"),
]
BUILD = [
    ("data.merge_recruits", "Stamp recruit_rank onto every player file"),
    ("data.merge_combine", "Stamp combine measurements onto player files"),
    ("model.rerank", "Score + classify + scarcity for the current season"),
    ("model.rerank_history", "Score historical seasons (for backtesting)"),
    ("analytics.predict", "ML model: NBA success / bust probabilities -> players.json"),
]


def _run(module: str, desc: str) -> None:
    print(f"\n{'='*70}\n>> {module}  —  {desc}\n{'='*70}")
    result = subprocess.run([sys.executable, "-m", module])
    if result.returncode != 0:
        print(f"\n!! {module} exited {result.returncode}; stopping pipeline.")
        sys.exit(result.returncode)


def _plan() -> None:
    print(__doc__)
    print("ACQUIRE (network):")
    for s, d in ACQUIRE:
        print(f"   {s:28s} {d}")
    print("\nBUILD (local recompute):")
    for s, d in BUILD:
        print(f"   {s:28s} {d}")


def main() -> None:
    args = sys.argv[1:]
    if "--plan" in args or "--help" in args or "-h" in args:
        _plan()
        return
    stage = args[0] if args else "build"

    if stage == "test":
        sys.exit(subprocess.run([sys.executable, "-m", "pytest"]).returncode)

    steps = []
    if stage == "scrape":
        steps = ACQUIRE + BUILD
    elif stage == "build":
        steps = BUILD
    else:
        print(f"Unknown stage '{stage}'. Try: build | scrape | test | --plan")
        sys.exit(2)

    for module, desc in steps:
        _run(module, desc)
    print(f"\n{'='*70}\nPipeline '{stage}' complete. Launch with: python app.py\n{'='*70}")


if __name__ == "__main__":
    main()
