#!/usr/bin/env python3
"""
High School Recruiting Rankings Scraper
----------------------------------------
Scrapes Wikipedia's McDonald's All-American Boys Game pages (top 24 HS recruits
per class year) plus the per-year recruiting class pages where available.

These are the highest-leverage non-stats input scouts actually use. A consensus
top-5 recruit becoming an NBA star is dramatically more likely than a #150
recruit becoming a star — recruit rank encodes years of accumulated scouting
that no college box score captures.

Usage:
    python scrape_recruits.py             # all default HS classes (2017-2025)
    python scrape_recruits.py 2019 2022   # subset

Output: recruits/recruits_<hs_class_year>.json
"""

import json
import re
import sys
import time
import unicodedata
from pathlib import Path

import requests
from bs4 import BeautifulSoup

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

from core.config import RECRUITS_DIR as OUT_DIR

DEFAULT_YEARS = list(range(2017, 2026))
DELAY = 1.5

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120.0",
    "Accept-Language": "en-US,en;q=0.9",
}


from core.names import normalize_name as _norm


def _get(url: str) -> str:
    r = requests.get(url, headers=HEADERS, timeout=20)
    r.raise_for_status()
    return r.text


def scrape_mcdonalds(year: int) -> list[dict]:
    """Scrape the McDonald's All-American roster for an HS class year.

    The Wikipedia page is at URL: /YYYY_McDonald%27s_All-American_Boys_Game
    """
    url = f"https://en.wikipedia.org/wiki/{year}_McDonald%27s_All-American_Boys_Game"
    print(f"  Fetching {url}")
    try:
        html = _get(url)
    except Exception as e:
        print(f"    !! Failed: {e}")
        return []

    soup = BeautifulSoup(html, "html.parser")
    recruits: list[dict] = []
    # The roster is in <table class="wikitable"> with columns including ESPN rank
    for table in soup.find_all("table", class_="wikitable"):
        headers = [th.get_text(" ", strip=True).lower() for th in table.find_all("th")]
        if not any("espn" in h or "rank" in h or "name" in h or "player" in h for h in headers):
            continue
        # Find column indices
        for tr in table.find("tbody").find_all("tr"):
            cells = tr.find_all(["td", "th"])
            if len(cells) < 3:
                continue
            text_cells = [c.get_text(" ", strip=True) for c in cells]
            # Find an ESPN rank (small int) in any cell
            rank = None
            for c in text_cells:
                m = re.match(r"^(\d{1,3})$", c)
                if m and 1 <= int(m.group(1)) <= 110:
                    rank = int(m.group(1))
                    break
            # Find a player name — usually a cell with a link to a player page
            name = None
            for c in cells:
                links = c.find_all("a")
                for a in links:
                    txt = a.get_text(" ", strip=True)
                    if (txt and len(txt.split()) >= 2 and
                            not any(skip in txt.lower() for skip in
                                    ("high", "school", "college", "wiki", "edit"))):
                        name = txt
                        break
                if name: break
            if not name or rank is None:
                continue
            college = ""
            for c in text_cells:
                if "→" in c or "->" in c:
                    college = c.split("→")[-1].split("->")[-1].strip()
                    break
            recruits.append({
                "name": name,
                "norm_name": _norm(name),
                "espn_rank": rank,
                "college_commit": college,
                "source": "mcdonalds_all_american",
                "hs_class_year": year,
            })

    return recruits


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    years = [int(a) for a in args] if args else DEFAULT_YEARS

    OUT_DIR.mkdir(exist_ok=True)
    print(f"Scraping HS recruiting data for classes: {years}")
    print("=" * 60)

    summary = []
    for y in years:
        recruits = scrape_mcdonalds(y)
        recruits.sort(key=lambda r: r["espn_rank"])
        out = OUT_DIR / f"recruits_{y}.json"
        out.write_text(json.dumps({
            "hs_class_year": y,
            "count": len(recruits),
            "recruits": recruits,
        }, indent=2, ensure_ascii=False), encoding="utf-8")
        print(f"  {y}: {len(recruits)} recruits → {out.name}")
        summary.append((y, len(recruits)))
        time.sleep(DELAY)

    print("\nSummary:")
    for y, n in summary:
        print(f"  HS class {y}: {n} recruits")


if __name__ == "__main__":
    main()
