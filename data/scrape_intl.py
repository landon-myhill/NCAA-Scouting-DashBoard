#!/usr/bin/env python3
"""
Targeted international-prospect scraper.

For each name on a season's curated board list (datasets/board_lists/
board_<year>.txt) that has NO NCAA record, search basketball-reference.com —
its /international/ section covers EuroLeague, EuroCup, ACB, LBA, LNB, ABA,
BSL, NBL and more — and pull the player's bio + most recent season per-game
stats. Output goes to datasets/intl/intl_<year>.json, which web/store.py
merges onto the board's international stub rows.

Deliberately TARGETED (a dozen names, ~30s) rather than scraping whole
leagues: we only need the players on the user's board.

Usage:
    python -m data.scrape_intl            # current season's list
    python -m data.scrape_intl 2025       # a specific year's list
"""

import json
import re
import sys
import time
from datetime import datetime

import requests
from bs4 import BeautifulSoup, Comment

from core import SEASON_YEAR, flt, load_json, pct
from core.config import BOARD_LISTS_DIR, HISTORY_DIR, INTL_DIR, PLAYERS_FILE
from core.names import normalize_name

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

BASE = "https://www.basketball-reference.com"
DELAY = 2.0
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120.0",
    "Accept-Language": "en-US,en;q=0.9",
}

# bbref per-game column -> our stats key (percentages handled separately)
_STAT_MAP = {
    "pts_per_g": "PPG", "trb_per_g": "RPG", "ast_per_g": "APG",
    "stl_per_g": "SPG", "blk_per_g": "BPG", "mp_per_g": "MPG",
    "tov_per_g": "TOV", "fg3a_per_g": "3PA", "fga_per_g": "FGA",
    "fta_per_g": "FTA",
}
_PCT_MAP = {"fg_pct": "FG%", "fg3_pct": "3P%", "ft_pct": "FT%"}


def _board_names(year: int) -> list[tuple[str, str]]:
    path = BOARD_LISTS_DIR / f"board_{year}.txt"
    if not path.exists():
        sys.exit(f"No board list for {year}: {path}")
    out = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.split("#")[0].strip()
        if line:
            name, _, school = (s.strip() for s in line.partition("|"))
            out.append((name, school))
    return out


def _ncaa_norms(year: int) -> set:
    path = PLAYERS_FILE if year == SEASON_YEAR else HISTORY_DIR / f"players_{year}.json"
    if not path.exists():
        return set()
    return {normalize_name(p["name"]) for p in load_json(path)["players"]}


def _get(url: str, **kw) -> requests.Response:
    r = requests.get(url, headers=HEADERS, timeout=20, **kw)
    r.raise_for_status()
    r.encoding = "utf-8"
    return r


def _find_player_page(name: str):
    """Search bbref; return (soup, url) of the international/G-League player
    page, or (None, None). Verifies the surname so we never grab a stranger.

    Players who later made the NBA (Wembanyama, Scoot, the Thompsons) redirect
    to their NBA page, hiding their pre-draft pages — so we also try the
    deterministic fallbacks: /international/players/<kebab-name>-1.html and
    /gleague/players/<x>/<nba-slug>d.html."""
    r = _get(f"{BASE}/search/", params={"search": name})
    if "/international/players/" in r.url or "/gleague/players/" in r.url:
        return [(BeautifulSoup(r.text, "html.parser"), r.url)]

    candidates = []
    # Results page: international/G-League hits
    links = re.findall(r'href="(/(?:international|gleague)/players/[^"]+\.html)"', r.text)
    want_last = normalize_name(name).split()[-1]
    candidates += [h for h in links if want_last in h.replace("-", " ")]
    # NBA-page redirect (or NBA hits in results): derive pre-draft page URLs
    nba_slugs = re.findall(r"/players/([a-z])/(\w+)\.html", r.url) or \
                re.findall(r'href="/players/([a-z])/(\w+)\.html"', r.text)
    if nba_slugs:
        x, slug = nba_slugs[0]
        if want_last[:5] in slug:
            candidates.append(f"/gleague/players/{x}/{slug}d.html")
    kebab = "-".join(normalize_name(name).split())
    candidates.append(f"/international/players/{kebab}-1.html")

    seen, pages = set(), []
    for href in candidates:
        if href in seen:
            continue
        seen.add(href)
        time.sleep(DELAY)
        try:
            r2 = _get(BASE + href)
        except Exception:
            continue
        pages.append((BeautifulSoup(r2.text, "html.parser"), r2.url))
    return pages


def find_best_record(name: str, draft_year: int):
    """Try every candidate page; return the first record with a real
    pre-draft season (>=3 games)."""
    pages = _find_player_page(name)
    if pages and not isinstance(pages, list):  # direct redirect
        pages = [pages]
    best = None
    for soup, url in pages or []:
        rec = _parse_player(soup, url, name, draft_year)
        if rec and (rec["stats"].get("G") or 0) >= 3:
            return rec
        best = best or rec
    return best


def _all_tables(soup: BeautifulSoup):
    tables = list(soup.find_all("table"))
    for c in soup.find_all(string=lambda t: isinstance(t, Comment)):
        tables += BeautifulSoup(str(c), "html.parser").find_all("table")
    return tables


def _parse_player(soup: BeautifulSoup, url: str, name: str,
                  draft_year: int | None = None) -> dict | None:
    meta = soup.find("div", id="meta")
    # bbref uses non-breaking spaces in the bio line — normalize them first
    meta_text = meta.get_text(" ", strip=True).replace("\xa0", " ") if meta else ""
    pos = None
    m = re.search(r"Position:(.*?)(?:Born:|Shoots:|$)", meta_text)
    if m:
        seg = m.group(1)
        hits = {k: seg.find(w) for w, k in
                (("Guard", "G"), ("Forward", "F"), ("Center", "C")) if w in seg}
        if hits:
            pos = min(hits, key=hits.get)  # first-mentioned position wins
    born = None
    m = re.search(r"Born:\s*(\w+\s+\d{1,2},\s+\d{4})", meta_text)
    if m:
        born = datetime.strptime(re.sub(r"\s+", " ", m.group(1)), "%B %d, %Y").date().isoformat()

    # Regular-season per-game table (the '_p'/'_post' variants are playoffs).
    # Intl pages use 'player-stats-per_game-league-'; G-League pages use
    # NBA-style ids — accept any per-game table with the season/points cols.
    table = None
    for t in _all_tables(soup):
        tid = t.get("id") or ""
        if "per_game" in tid and not tid.endswith(("_p", "_post")):
            head = {th.get("data-stat") for th in (t.find("thead") or t).find_all("th")}
            if "pts_per_g" in head and ("season" in head or "year_id" in head):
                table = t
                break
    if table is None:
        return None
    rows = []
    for tr in table.find("tbody").find_all("tr"):
        row = {c.get("data-stat"): c.get_text(strip=True) for c in tr.find_all(["th", "td"])}
        if row.get("season"):
            rows.append(row)
    if not rows:
        return None

    def _end_year(season: str):
        m = re.match(r"(\d{4})(?:-(\d{2}))?", season)
        if not m:
            return None
        return int(m.group(1)[:2] + m.group(2)) if m.group(2) else int(m.group(1))

    # PRE-DRAFT seasons only: NBA players' G-League pages include post-draft
    # assignment stints (Leonard Miller showed a 2025-26 row on his 2023 card)
    if draft_year:
        rows = [r for r in rows if (_end_year(r["season"]) or 0) <= draft_year]
        if not rows:
            return None  # only post-draft stints here — honest absence beats wrong stats
    latest = max(r["season"] for r in rows)
    season_rows = [r for r in rows if r["season"] == latest]
    # Primary row = where he actually played (most total minutes)
    primary = max(season_rows, key=lambda r: flt(r.get("g"), 0) * flt(r.get("mp_per_g"), 0))

    stats = {our: flt(primary.get(bb)) for bb, our in _STAT_MAP.items()}
    stats.update({our: pct(primary.get(bb)) for bb, our in _PCT_MAP.items()})
    stats["G"] = int(flt(primary.get("g"), 0))

    age_label = None
    if born:
        age = (datetime.now().date() - datetime.fromisoformat(born).date()).days // 365
        age_label = f"Age {age}"

    return {
        "name": name,
        "norm_name": normalize_name(name),
        "pos": pos,
        "born": born,
        "age_label": age_label,
        "team": primary.get("team") or primary.get("team_id"),
        "league": primary.get("league") or primary.get("lg_id"),
        "season": latest,
        "stats": stats,
        "all_rows": [{k: r.get(k) for k in ("season", "team", "league", "g", "mp_per_g", "pts_per_g")}
                     for r in rows],
        "source": url,
    }


def main():
    args = [a for a in sys.argv[1:] if a.isdigit()]
    years = [int(a) for a in args] if args else [SEASON_YEAR]
    for year in years:
        run_year(year)


def run_year(year: int):
    ncaa = _ncaa_norms(year)
    targets = [(n, club) for n, club in _board_names(year)
               if normalize_name(n) not in ncaa]
    print(f"Board {year}: {len(targets)} listed prospects without NCAA data")

    players, missed = [], []
    for i, (name, club) in enumerate(targets, 1):
        print(f"  [{i}/{len(targets)}] {name} ({club or '?'}) ... ", end="", flush=True)
        try:
            rec = find_best_record(name, year)
            if rec:
                s = rec["stats"]
                print(f"{rec['season']} {rec['team']} ({rec['league']}): "
                      f"{s.get('PPG')} ppg / {s.get('RPG')} rpg in {s.get('MPG')} mpg")
                players.append(rec)
            else:
                print("not found on basketball-reference")
                missed.append(name)
        except Exception as e:
            print(f"ERROR: {e}")
            missed.append(name)
        time.sleep(DELAY)

    INTL_DIR.mkdir(parents=True, exist_ok=True)
    out = INTL_DIR / f"intl_{year}.json"
    out.write_text(json.dumps({
        "year": year,
        "scraped_at": datetime.now().isoformat(),
        "players": players,
        "missed": missed,
    }, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"\nWrote {len(players)} players to {out.name}" +
          (f" ({len(missed)} not found: {', '.join(missed)})" if missed else ""))


if __name__ == "__main__":
    main()
