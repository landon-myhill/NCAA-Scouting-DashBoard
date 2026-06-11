#!/usr/bin/env python3
"""
Historical NCAA Stats Backfill
-------------------------------
Scrapes prior seasons (default: 2020-2025) and stores each in
history/players_<year>.json. Used by analyze_history.py to backtest the
formula against actual NBA draft outcomes.

Usage:
    python -m data.scrape_history                  # scrape all default years
    python -m data.scrape_history 2025             # scrape just 2025
    python -m data.scrape_history 2022 2023 2024   # scrape a subset
    python -m data.scrape_history --force          # re-scrape even if files exist

Each year takes ~12-15 minutes due to sports-reference's 2s rate limit.
"""

import sys

from core import HISTORY_DIR
from data.scrape import scrape_year

DEFAULT_YEARS = [2020, 2021, 2022, 2023, 2024, 2025]


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    force = "--force" in sys.argv

    years = [int(a) for a in args] if args else DEFAULT_YEARS

    HISTORY_DIR.mkdir(exist_ok=True)
    print(f"Backfilling NCAA seasons: {years}")
    print(f"Output dir: {HISTORY_DIR}")
    print(f"Skip-if-exists: {not force}")
    print("=" * 54)

    results = []
    for year in years:
        out_file = HISTORY_DIR / f"players_{year}.json"
        try:
            n = scrape_year(year, out_file, skip_if_exists=not force, stop_on_error=False)
            results.append((year, n, "ok"))
        except Exception as e:
            results.append((year, 0, f"FAILED: {e}"))
            print(f"\n!! {year} failed: {e}")
            print("   Continuing to next year. Re-run with `python scrape_history.py "
                  f"{year}` to retry.")

    print("\n" + "=" * 54)
    print("Backfill summary:")
    for year, n, status in results:
        print(f"  {year}: {n:>5} players  [{status}]")


if __name__ == "__main__":
    main()
