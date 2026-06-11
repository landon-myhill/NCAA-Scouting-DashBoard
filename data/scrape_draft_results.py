#!/usr/bin/env python3
"""
NBA Draft Results + Post-Draft Career Scraper
----------------------------------------------
For each draft year, scrapes basketball-reference.com/draft/NBA_<year>.html to
get the actual draft results (pick #, player, college, basic career totals).

The career totals come directly from the draft page's "Career stats" columns:
years played, games, minutes, points, total Win Shares, BPM, VORP. This gives
us enough to measure "did this player become an NBA contributor?" without
having to scrape every individual NBA player page.

For undrafted-but-NBA players (the Jokić-level miss for our formula), we'd
need to scrape further, but the great majority of NBA contributors are drafted.

Usage:
    python scrape_draft_results.py                  # all default years
    python scrape_draft_results.py 2023 2024 2025   # subset
"""

import json
import re
import sys
import time
from pathlib import Path

import requests
from bs4 import BeautifulSoup, Comment

from core import HISTORY_DIR

DEFAULT_YEARS = [2020, 2021, 2022, 2023, 2024, 2025]
BASE = "https://www.basketball-reference.com"
DELAY = 2.0

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120.0",
    "Accept-Language": "en-US,en;q=0.9",
}


def _get(url: str) -> str:
    r = requests.get(url, headers=HEADERS, timeout=20)
    r.raise_for_status()
    r.encoding = "utf-8"
    return r.text


def _flt(v):
    if not v or str(v).strip() in ("", "—", "-"):
        return None
    try:
        return float(v)
    except (ValueError, TypeError):
        return None


def _parse_table(soup: BeautifulSoup, table_id: str):
    """Parse a basketball-reference stats table by id, including ones in comments."""
    table = soup.find("table", {"id": table_id})
    if not table:
        for comment in soup.find_all(string=lambda t: isinstance(t, Comment)):
            inner = BeautifulSoup(str(comment), "html.parser")
            table = inner.find("table", {"id": table_id})
            if table:
                break
    if not table or not table.find("tbody"):
        return []
    rows = []
    for tr in table.find("tbody").find_all("tr"):
        if "thead" in tr.get("class", []):
            continue
        row = {c.get("data-stat"): c.get_text(strip=True)
               for c in tr.find_all(["th", "td"]) if c.get("data-stat")}
        rows.append(row)
    return rows


def scrape_draft_year(year: int) -> list[dict]:
    """
    Scrape one NBA draft year. Returns list of pick records with embedded
    career stats.
    """
    url = f"{BASE}/draft/NBA_{year}.html"
    print(f"  Fetching {url}")
    html = _get(url)
    soup = BeautifulSoup(html, "html.parser")

    rows = _parse_table(soup, "stats")
    picks = []
    for r in rows:
        pick_no = r.get("pick_overall") or r.get("pick")
        if not pick_no:
            continue
        try:
            pick_overall = int(pick_no)
        except ValueError:
            continue
        name = r.get("player") or r.get("name_display") or ""
        if not name:
            continue
        college = r.get("college_name") or r.get("college") or ""
        team = r.get("team_id") or r.get("team_name") or ""

        # Career totals (post-draft NBA production)
        picks.append({
            "year": year,
            "pick_overall": pick_overall,
            "round": int(r.get("round", 0)) if r.get("round","").isdigit() else (1 if pick_overall <= 30 else 2),
            "player": name,
            "team": team,
            "college": college,
            "career": {
                "years": _flt(r.get("years_played")),
                "games": _flt(r.get("g")),
                "minutes": _flt(r.get("mp")),
                "points_total": _flt(r.get("pts")),
                "rebounds_total": _flt(r.get("trb")),
                "assists_total": _flt(r.get("ast")),
                "WS": _flt(r.get("ws") or r.get("win_shares")),
                "WS/48": _flt(r.get("ws_per_48")),
                "BPM": _flt(r.get("bpm")),
                "VORP": _flt(r.get("vorp")),
                "PPG": _flt(r.get("pts_per_g")),
                "RPG": _flt(r.get("trb_per_g")),
                "APG": _flt(r.get("ast_per_g")),
            },
        })

    return picks


def career_tier(career: dict) -> str:
    """
    Classify NBA outcome into a coarse tier we can use for steals analysis.
    Uses career VORP and WS as the headline signals.
    """
    if not career:
        return "no_nba"
    vorp = career.get("VORP") or 0
    ws = career.get("WS") or 0
    games = career.get("games") or 0
    years = career.get("years") or 0

    # Tiers calibrated for 2-5 year careers (2020-2023 drafts).
    if vorp >= 10 or ws >= 35:
        return "star"            # All-Star / All-NBA caliber
    if vorp >= 4 or ws >= 18 or games >= 300:
        return "starter"         # multi-year starter / strong rotation
    if vorp >= 0.5 or ws >= 5 or games >= 100:
        return "rotation"        # NBA rotation player
    if years >= 1 or games >= 10:
        return "bench"           # brief NBA stint
    return "no_nba"              # drafted but never played


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    years = [int(a) for a in args] if args else DEFAULT_YEARS

    HISTORY_DIR.mkdir(exist_ok=True)
    print(f"Scraping NBA draft results for: {years}")
    print("=" * 54)

    results = []
    for y in years:
        out_file = HISTORY_DIR / f"draft_results_{y}.json"
        try:
            picks = scrape_draft_year(y)
        except Exception as e:
            print(f"  !! {y} failed: {e}")
            results.append((y, 0))
            continue

        # Tag career tier
        for p in picks:
            p["career_tier"] = career_tier(p["career"])

        out_file.write_text(json.dumps({
            "year": y,
            "pick_count": len(picks),
            "picks": picks,
        }, indent=2, ensure_ascii=False), encoding="utf-8")

        # Quick summary
        from collections import Counter
        tier_counts = Counter(p["career_tier"] for p in picks)
        print(f"  {y}: {len(picks)} picks  " +
              "  ".join(f"{t}={tier_counts[t]}" for t in ["star","starter","rotation","bench","no_nba"]))
        results.append((y, len(picks)))
        time.sleep(DELAY)

    print("\nDone.")
    for y, n in results:
        print(f"  {y}: {n} picks")


if __name__ == "__main__":
    main()
