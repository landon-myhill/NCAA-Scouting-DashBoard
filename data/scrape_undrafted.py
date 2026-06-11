#!/usr/bin/env python3
"""
Scrape NBA outcomes for top college players who went UNDRAFTED.

Why: the eval/training set only contains drafted players, so the models never
learn from the players the NBA skipped (or wrongly skipped). For each mature
draft class, take our top-150 board, drop everyone who was drafted, and check
basketball-reference for an NBA page:

  - found + college matches  -> real outcome (career WS/VORP/games -> tier)
  - not found                -> outcome = no_nba (that IS the signal)

Output: datasets/history/undrafted_results_<year>.json, folded into the
backtest by analytics.backtest.load_matched(include_undrafted=True).

Usage:
    python -m data.scrape_undrafted              # all mature years (2020-2023)
    python -m data.scrape_undrafted 2022         # one year
"""

import json
import re
import sys
import time
from datetime import datetime

import requests
from bs4 import BeautifulSoup, Comment

from core import HISTORY_DIR, load_json
from core.config import MATURE_DRAFT_YEARS
from core.names import normalize_name
from data.scrape_draft_results import career_tier

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

BASE = "https://www.basketball-reference.com"
DELAY = 2.5
TOP_N = 150
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120.0",
    "Accept-Language": "en-US,en;q=0.9",
}


def _get(url: str, **kw) -> requests.Response:
    r = requests.get(url, headers=HEADERS, timeout=20, **kw)
    r.raise_for_status()
    r.encoding = "utf-8"
    return r


def _flt(v):
    try:
        return float(v) if str(v).strip() not in ("", "—", "-") else None
    except (ValueError, TypeError):
        return None


def _career_from_page(soup: BeautifulSoup) -> dict | None:
    """Career WS/VORP/games from the advanced table's Career footer row."""
    table = soup.find("table", id="advanced")
    if not table:
        for c in soup.find_all(string=lambda t: isinstance(t, Comment)):
            table = BeautifulSoup(str(c), "html.parser").find("table", id="advanced")
            if table:
                break
    if not table or not table.find("tfoot"):
        return None
    for tr in table.find("tfoot").find_all("tr"):
        cells = {c.get("data-stat"): c.get_text(strip=True) for c in tr.find_all(["th", "td"])}
        # bbref labels the career footer row "Career" or "N Yrs"
        label = cells.get("season") or cells.get("year_id") or ""
        m = re.match(r"(\d+)\s*Yrs?", label)
        if "Career" in label or m:
            return {
                "years": int(m.group(1)) if m else None,
                "games": _flt(cells.get("games") or cells.get("g")),
                "WS": _flt(cells.get("ws")),
                "VORP": _flt(cells.get("vorp")),
            }
    return None


def _college_matches(soup: BeautifulSoup, school: str) -> bool:
    meta = soup.find("div", id="meta")
    if not meta:
        return False
    text = meta.get_text(" ", strip=True).replace("\xa0", " ")
    m = re.search(r"Colleges?:\s*(.+?)(?:High School|Draft|Recruiting|NBA Debut|$)", text)
    if not m:
        return False
    page_college = normalize_name(m.group(1))
    want = normalize_name(school)
    return want in page_college or page_college in want


def _debuted_after(soup: BeautifulSoup, year: int) -> bool:
    """Reject pages whose career started before the player's college year
    (same-name veteran). First season in per_game table must be >= year-1."""
    table = soup.find("table", id="per_game_stats") or soup.find("table", id="per_game")
    if not table or not table.find("tbody"):
        return True  # can't tell; rely on college match
    for tr in table.find("tbody").find_all("tr"):
        th = tr.find("th")
        m = re.match(r"(\d{4})", th.get_text(strip=True) if th else "")
        if m:
            return int(m.group(1)) >= year - 1
    return True


def _find_nba_outcome(name: str, school: str, year: int):
    """Return (career_dict or None, matched_url or None)."""
    r = _get(f"{BASE}/search/", params={"search": name})
    candidates = []
    if re.search(r"/players/[a-z]/\w+\.html", r.url):
        candidates = [r.url]
        page = BeautifulSoup(r.text, "html.parser")
        if _college_matches(page, school) and _debuted_after(page, year):
            return _career_from_page(page), r.url
        return None, None
    # results page: NBA player links only (ignore /cbb/ college links).
    # bbref slugs truncate the surname to 5 chars (reaveau01), so match on
    # the first 5 letters, not the full name.
    hrefs = re.findall(r'href="(/players/[a-z]/\w+\.html)"', r.text)
    want_last = normalize_name(name).split()[-1].replace("'", "")[:5]
    seen = set()
    for href in hrefs:
        if href in seen or want_last not in href:
            continue
        seen.add(href)
        time.sleep(DELAY)
        page = BeautifulSoup(_get(BASE + href).text, "html.parser")
        if _college_matches(page, school) and _debuted_after(page, year):
            return _career_from_page(page), BASE + href
        if len(seen) >= 2:  # at most two candidate fetches per name
            break
    return None, None


def _drafted_any_year() -> set:
    """Names drafted in ANY scraped class. A 2020 top-150 player drafted in
    2021 (Franz Wagner) is NOT an undrafted outcome — he just left later."""
    drafted = set()
    for f in HISTORY_DIR.glob("draft_results_*.json"):
        for p in load_json(f)["picks"]:
            drafted.add(normalize_name(p["player"]))
    return drafted


def scrape_year(year: int, drafted: set) -> None:
    players = load_json(HISTORY_DIR / f"players_{year}.json")["players"][:TOP_N]
    targets = [p for p in players if normalize_name(p["name"]) not in drafted]
    print(f"\n{year}: top {TOP_N} board, {len(targets)} never-drafted to check")

    out_rows, found = [], 0
    for i, p in enumerate(targets, 1):
        name, school = p["name"], p.get("school", "")
        print(f"  [{i}/{len(targets)}] {name} ({school}) ... ", end="", flush=True)
        career, url = None, None
        try:
            career, url = _find_nba_outcome(name, school, year)
        except Exception as e:
            print(f"ERROR {e} -> treating as no_nba", end="")
        tier = career_tier(career) if career else "no_nba"
        if career:
            found += 1
            print(f"NBA: {career.get('games')} g, WS {career.get('WS')} -> {tier}")
        else:
            print("no NBA record")
        out_rows.append({
            "year": year,
            "player": name,
            "college": school,
            "ncaa_rank": p.get("rank"),
            "career": career or {},
            "career_tier": tier,
            "source": url,
        })
        time.sleep(DELAY)

    out = HISTORY_DIR / f"undrafted_results_{year}.json"
    out.write_text(json.dumps({
        "year": year, "scraped_at": datetime.now().isoformat(),
        "top_n": TOP_N, "players": out_rows,
    }, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"{year}: wrote {len(out_rows)} undrafted outcomes ({found} reached the NBA) -> {out.name}")


def main():
    args = [a for a in sys.argv[1:] if a.isdigit()]
    years = [int(a) for a in args] if args else list(MATURE_DRAFT_YEARS)
    drafted = _drafted_any_year()
    print(f"Excluding {len(drafted)} players drafted in any class 2020-2025.")
    for y in years:
        scrape_year(y, drafted)


if __name__ == "__main__":
    main()
