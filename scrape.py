#!/usr/bin/env python3
"""
NCAA Basketball Data Scraper
-----------------------------
Fetches per-game and advanced stats from sports-reference.com
for all D1 players and saves to players.json.

Usage:
    python scrape.py

Scrapes each D1 team page (~365 schools). Takes ~8 minutes due to
polite rate limiting. Run once per season; the app reads players.json
at runtime with no API calls needed.
"""

import json
import re
import time
from datetime import datetime
from pathlib import Path

import requests
from bs4 import BeautifulSoup, Comment

from archetypes import draft_score

# ── Config ────────────────────────────────────────────────────────────────────

YEAR      = 2026       # End year for 2025-26 season
MIN_GAMES = 10         # Skip players with fewer games
OUT_FILE  = Path(__file__).parent / "players.json"
BASE      = "https://www.sports-reference.com"
DELAY     = 2.0        # Seconds between requests (2s reduces rate-limit risk)

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120.0",
    "Accept-Language": "en-US,en;q=0.9",
    "Accept": "text/html,application/xhtml+xml",
}

CLASS_MAP = {
    "FR": "Freshman",  "Fr": "Freshman",  "Fr.": "Freshman",
    "SO": "Sophomore", "So": "Sophomore", "So.": "Sophomore",
    "JR": "Junior",    "Jr": "Junior",    "Jr.": "Junior",
    "SR": "Senior",    "Sr": "Senior",    "Sr.": "Senior",
    "GR": "Graduate",  "Gr": "Graduate",  "Gr.": "Graduate",
}

# ── Helpers ───────────────────────────────────────────────────────────────────

def get(url: str) -> requests.Response:
    r = requests.get(url, headers=HEADERS, timeout=20)
    r.raise_for_status()
    return r


def flt(val, default=None):
    if not val or str(val).strip() in ("", "—", "-", "N/A", "."):
        return default
    try:
        return float(val)
    except (ValueError, TypeError):
        return default


def pct(val):
    """Convert decimal (0.452) to display value (45.2)."""
    v = flt(val)
    if v is None:
        return None
    return round(v * 100, 1) if 0 < v <= 1.0 else round(v, 1)


def parse_table(soup: BeautifulSoup, table_id: str) -> list[dict]:
    """Parse a stats table by id, also checking inside HTML comments."""
    table = soup.find("table", {"id": table_id})

    # Sports-reference hides some tables in HTML comments
    if not table:
        for comment in soup.find_all(string=lambda t: isinstance(t, Comment)):
            inner = BeautifulSoup(str(comment), "html.parser")
            table = inner.find("table", {"id": table_id})
            if table:
                break

    if not table:
        return []

    rows = []
    for tr in table.find("tbody").find_all("tr"):
        if "thead" in tr.get("class", []):
            continue
        row = {c.get("data-stat"): c.get_text(strip=True)
               for c in tr.find_all(["th", "td"]) if c.get("data-stat")}
        if row.get("name_display") or row.get("player"):
            rows.append(row)
    return rows


def derive_skills(ppg, rpg, apg, spg, bpg, fg, three, ft,
                  tov=None, efg=None, drb_pct=None) -> dict:
    fg    = fg    or 0
    three = three or 0
    ft    = ft    or 0
    efg_v = efg if efg is not None else fg   # eFG% weights 3s correctly; fall back to FG%

    # Shooting: eFG%, 3P%, FT%
    shooting = int(min(100, max(0,
        (efg_v - 35) / 30 * 40 +
        (three - 20) / 25 * 30 +
        (ft - 55)    / 35 * 30
    )))

    # Defense: steals, blocks, defensive rebounding %
    drb_v   = drb_pct or 0
    defense = int(min(100, max(0,
        (spg or 0) / 2.5 * 35 +
        (bpg or 0) / 3.0 * 35 +
        drb_v / 25.0 * 30
    )))

    # Ball handling: APG minus turnover penalty (>1.5 TOV/g hurts score)
    tov_v         = tov or 0
    tov_penalty   = min(30, max(0, (tov_v - 1.5) / 3.0 * 30))
    ball_handling = int(min(100, max(0, (apg or 0) / 9.0 * 100 - tov_penalty)))

    # Athleticism: steals + scoring
    athleticism = int(min(100, max(0, (spg or 0) / 2.5 * 40 + (ppg or 0) / 30.0 * 60)))

    # IQ: assists, shooting efficiency, low turnovers
    tov_bonus = max(0, 20 - tov_v * 4) if tov_v > 0 else 20
    iq        = int(min(100, max(0, (apg or 0) / 9.0 * 50 + efg_v / 65.0 * 30 + tov_bonus)))

    # Leadership: overall scoring + rebounding + playmaking production
    leadership = int(min(100, max(0,
        (rpg or 0) / 12 * 30 +
        (ppg or 0) / 30 * 50 +
        (apg or 0) / 9.0 * 20
    )))

    return {
        "Athleticism": athleticism, "Defense": defense, "Shooting": shooting,
        "Ball Handling": ball_handling, "IQ": iq, "Leadership": leadership,
    }


# ── School list ───────────────────────────────────────────────────────────────

def get_school_urls() -> list[tuple[str, str]]:
    """Return list of (url, school_name) tuples for all D1 schools."""
    print(f"  Fetching D1 school list for {YEAR}...")
    soup = BeautifulSoup(get(f"{BASE}/cbb/seasons/men/{YEAR}-school-stats.html").text, "html.parser")
    links = soup.find_all("a", href=re.compile(rf"/cbb/schools/.+/men/{YEAR}\.html"))
    seen = set()
    result = []
    for a in links:
        href = a["href"]
        if href in seen:
            continue
        seen.add(href)
        slug = href.split("/schools/")[1].split("/")[0]
        name = a.get_text(strip=True) or slug.replace("-", " ").title()
        result.append((f"{BASE}{href}", name))
    result.sort(key=lambda x: x[1])
    print(f"  Found {len(result)} D1 schools")
    return result


# ── Per-school scrape ─────────────────────────────────────────────────────────

def fmt_height(h: str) -> str:
    """Convert '6-7' to 6'7\" """
    if h and "-" in h and "'" not in h:
        parts = h.split("-", 1)
        return f"{parts[0]}'{parts[1]}\""
    return h or "—"


def scrape_school(url: str, school_name: str) -> list[dict]:
    soup = BeautifulSoup(get(url).text, "html.parser")

    # Conference — strip sport suffix e.g. "Big 12 MBB" -> "Big 12"
    conf_tag = soup.find("a", href=re.compile(r"/cbb/conferences/"))
    conf = re.sub(r"\s*(MBB|WBB|FB)$", "", conf_tag.get_text(strip=True)).strip() if conf_tag else "Unknown"

    # Roster table — has class, height, weight, hometown keyed by player name
    roster_rows = parse_table(soup, "roster")
    roster_lookup = {r["player"]: r for r in roster_rows if r.get("player")}

    pg_rows  = parse_table(soup, "players_per_game")
    adv_rows = parse_table(soup, "players_advanced")
    adv_lookup = {r["name_display"]: r for r in adv_rows if r.get("name_display")}

    players = []
    for row in pg_rows:
        name = row.get("name_display", "").strip()
        if not name:
            continue
        g = flt(row.get("games"), 0)
        if g < MIN_GAMES:
            continue

        # ── Per-game stats ─────────────────────────────────────────────────────
        ppg  = flt(row.get("pts_per_g"))
        rpg  = flt(row.get("trb_per_g"))
        apg  = flt(row.get("ast_per_g"))
        spg  = flt(row.get("stl_per_g"))
        bpg  = flt(row.get("blk_per_g"))
        fg_p = pct(row.get("fg_pct"))
        tp_p = pct(row.get("fg3_pct"))
        ft_p = pct(row.get("ft_pct"))
        mpg  = flt(row.get("mp_per_g"))
        gs   = flt(row.get("gs"), 0)
        tov  = flt(row.get("tov_per_g"))
        fta  = flt(row.get("fta_per_g"))
        oreb = flt(row.get("orb_per_g"))
        dreb = flt(row.get("drb_per_g"))
        tpa  = flt(row.get("fg3a_per_g"))   # 3-point attempts per game
        fga  = flt(row.get("fga_per_g"))    # field-goal attempts per game
        pf   = flt(row.get("pf_per_g"))

        # ── Advanced stats ──────────────────────────────────────────────────────
        adv     = adv_lookup.get(name, {})
        per     = flt(adv.get("per"))
        ts_p    = pct(adv.get("ts_pct"))
        efg_p   = pct(adv.get("efg_pct"))
        usg     = flt(adv.get("usg_pct"))
        ast_pct = flt(adv.get("ast_pct"))
        tov_pct = flt(adv.get("tov_pct"))
        ws      = flt(adv.get("ws"))
        ws40    = flt(adv.get("ws_per_40"))
        ows     = flt(adv.get("ows"))
        dws     = flt(adv.get("dws"))
        bpm     = flt(adv.get("bpm"))
        obpm    = flt(adv.get("obpm"))
        dbpm    = flt(adv.get("dbpm"))
        drb_pct = flt(adv.get("drb_pct"))

        # ── Roster / bio ────────────────────────────────────────────────────────
        # Try exact match first, then fuzzy (last name + first initial)
        ros = roster_lookup.get(name, {})
        if not ros:
            name_lower = name.lower().strip()
            for rname, rdata in roster_lookup.items():
                if rname.lower().strip() == name_lower:
                    ros = rdata
                    break
                # Match if one is a substring of the other (handles Jr., III, etc.)
                if name_lower in rname.lower() or rname.lower() in name_lower:
                    ros = rdata
                    break
        cls      = CLASS_MAP.get(ros.get("class", "").strip(), "Unknown")
        ht       = fmt_height(ros.get("height", ""))
        wt       = f"{ros.get('weight', '')} lbs".strip() if ros.get("weight") else "—"
        hometown = ros.get("birth_place", "") or "—"

        players.append({
            "name":       name,
            "pos":        row.get("pos", "?").strip() or "?",
            "school":     school_name,
            "conference": conf,
            "year":       cls,
            "height":     ht,
            "weight":     wt,
            "hometown":   hometown,
            "stats": {
                "PPG": ppg, "RPG": rpg, "APG": apg,
                "SPG": spg, "BPG": bpg,
                "FG%": fg_p, "3P%": tp_p, "FT%": ft_p,
                "MPG": mpg, "GS": int(gs) if gs else None,
                "TOV": tov, "FTA": fta,
                "OREB": oreb, "DREB": dreb,
                "3PA": tpa, "FGA": fga, "PF": pf,
            },
            "advanced": {
                "PER": per, "TS%": ts_p, "eFG%": efg_p, "USG%": usg,
                "AST%": ast_pct, "TOV%": tov_pct,
                "BPM": bpm, "OBPM": obpm, "DBPM": dbpm,
                "OWS": ows, "DWS": dws, "Win Shares": ws, "WS/40": ws40,
            },
            "skills":    derive_skills(ppg, rpg, apg, spg, bpg, fg_p, tp_p, ft_p,
                                       tov=tov, efg=efg_p, drb_pct=drb_pct),
            "strengths": [], "weaknesses": [], "comps": [],
            "injury":    "Clean",
        })

    return players


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    print(f"\nNCAA Basketball Scraper — {YEAR - 1}-{str(YEAR)[2:]} Season")
    print("=" * 54)

    time.sleep(DELAY)
    schools = get_school_urls()
    total   = len(schools)

    print(f"\nScraping {total} school pages (~{round(total * DELAY / 60, 1)} min)...")
    print("-" * 54)

    all_players: list[dict] = []
    errors = 0

    for i, (url, name) in enumerate(schools, 1):
        bar = "#" * int(i / total * 20) + "-" * (20 - int(i / total * 20))
        print(f"\r  [{bar}] {i}/{total}  {name:<35}", end="", flush=True)
        try:
            all_players.extend(scrape_school(url, name))
        except Exception as e:
            print(f"\n\n  ERROR on {name}: {e}")
            print(f"  Stopping. {len(all_players)} players collected so far.")
            break
        time.sleep(DELAY)

    print(f"\n\nCollected {len(all_players)} players ({errors} school errors)")

    # Sort by composite draft score, assign IDs/ranks/tiers
    for p in all_players:
        p["draft_score"] = draft_score(p)
    all_players.sort(key=lambda p: p["draft_score"], reverse=True)
    for i, p in enumerate(all_players):
        p["id"]   = i + 1
        p["rank"] = i + 1
        p["tier"] = 1 if i < 15 else (2 if i < 45 else 3)

    output = {
        "scraped_at":   datetime.now().isoformat(),
        "season":       f"{YEAR - 1}-{str(YEAR)[2:]}",
        "player_count": len(all_players),
        "players":      all_players,
    }

    with open(OUT_FILE, "w", encoding="utf-8") as f:
        json.dump(output, f, indent=2, ensure_ascii=False)

    print(f"Saved {len(all_players)} players to {OUT_FILE.name}")
    print(f"Top 5: {', '.join(p['name'] for p in all_players[:5])}")
    print(f"Done:  {output['scraped_at']}")


if __name__ == "__main__":
    main()
