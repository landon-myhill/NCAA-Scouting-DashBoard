"""
Read-only player data store. Loads players.json / scarcity.json once at
import, history years lazily with caching, and pre-sorts stat values so
percentile lookups are O(log n). Routes must treat everything here as
immutable — copy before annotating (see views.bigboard).
"""

import json
import re
from bisect import bisect_left

from core import HISTORY_DIR, PLAYERS_FILE, SCARCITY_FILE, SEASON_YEAR, season_label_for
from core.config import BOARD_LISTS_DIR, INTL_DIR, MATURE_DRAFT_YEARS
from core.names import match_player, name_keys, normalize_name
from model.archetypes import DEFAULT_WEIGHTS, classify, combine_parts, draft_score

CURRENT_SEASON_YEAR = SEASON_YEAR  # active draft cycle (env-overridable)


def _load_players() -> list[dict]:
    if not PLAYERS_FILE.exists():
        return []
    raw = json.loads(PLAYERS_FILE.read_text(encoding="utf-8"))
    return raw.get("players", [])


def _load_scarcity() -> dict:
    if not SCARCITY_FILE.exists():
        return {}
    return json.loads(SCARCITY_FILE.read_text(encoding="utf-8"))


def _load_history_year(year: int):
    """Load a historical season's players list (or None if not scraped yet)."""
    path = HISTORY_DIR / f"players_{year}.json"
    if not path.exists():
        return None, None
    raw = json.loads(path.read_text(encoding="utf-8"))
    players = raw.get("players", [])
    _attach_nba_outcomes(players, year)
    return players, raw.get("season", season_label_for(year))


def _attach_nba_outcomes(players: list[dict], year: int) -> None:
    """Stamp what ACTUALLY happened (draft pick + career tier) onto a
    historical season, so the board shows hindsight next to the model's
    rank. Load-time enrichment of the cached year — not request state."""
    path = HISTORY_DIR / f"draft_results_{year}.json"
    if not path.exists():
        return
    picks = json.loads(path.read_text(encoding="utf-8")).get("picks", [])
    by_norm = {normalize_name(p["name"]): p for p in players}
    by_school: dict = {}
    for p in players:
        p["_draft_complete"] = True  # this year's draft results exist
        by_school.setdefault(p.get("school", ""), []).append(p)
    mature = year in MATURE_DRAFT_YEARS
    for pick in picks:
        rec = match_player(pick, by_norm, by_school)
        if rec is not None:
            rec["nba"] = {"pick": pick.get("pick_overall"),
                          "tier": pick.get("career_tier"),
                          "mature": mature}


def available_years():
    """Return [(year, label, is_current), ...] in descending order. Current
    season is always first; historical years are listed only if scraped."""
    out = [(CURRENT_SEASON_YEAR, f"{season_label_for(CURRENT_SEASON_YEAR)} (current)", True)]
    if HISTORY_DIR.exists():
        years = []
        for f in HISTORY_DIR.glob("players_*.json"):
            m = re.search(r"players_(\d{4})\.json", f.name)
            if m:
                y = int(m.group(1))
                if y != CURRENT_SEASON_YEAR:
                    years.append(y)
        for y in sorted(years, reverse=True):
            out.append((y, season_label_for(y), False))
    return out


PLAYERS = _load_players()
PLAYERS_BY_ID = {p["id"]: p for p in PLAYERS}
SCARCITY = _load_scarcity()

# Cache of historical years loaded on demand. Each entry holds the players
# list and a {id: profile} map so we don't reclassify on every request.
_YEAR_CACHE: dict[int, dict] = {}


def get_profile(p: dict) -> dict:
    """Archetype profile, preferring what rerank precomputed into the file."""
    if p.get("_intl_stub"):
        return {"primary": "", "defensive": "", "all_offensive": [],
                "all_defensive": [], "tags": [], "red_flags": []}
    if "archetype" in p:
        return {
            "primary": p["archetype"],
            "defensive": p.get("defensive_archetype", ""),
            "all_offensive": p.get("all_offensive", [p["archetype"]]),
            "all_defensive": p.get("all_defensive", [p.get("defensive_archetype", "")]),
            "tags": p.get("tags", []),
            "red_flags": p.get("red_flags", []),
        }
    return classify(p)


PROFILES = {p["id"]: get_profile(p) for p in PLAYERS}


def get_year_data(year):
    """Return (players_list, profiles_map, season_label).

    `year` accepts an int (specific season) or the string "all" (combined
    cross-year master board). Returns (None, None, None) if the year hasn't
    been scraped yet.
    """
    if year == "all":
        return _get_all_years_data()
    if year is None or year == CURRENT_SEASON_YEAR:
        return PLAYERS, PROFILES, season_label_for(CURRENT_SEASON_YEAR)
    if year in _YEAR_CACHE:
        c = _YEAR_CACHE[year]
        return c["players"], c["profiles"], c["season"]
    players, season = _load_history_year(year)
    if players is None:
        return None, None, None
    profiles = {p["id"]: get_profile(p) for p in players}
    _YEAR_CACHE[year] = {"players": players, "profiles": profiles, "season": season}
    return players, profiles, season


def _get_all_years_data():
    """Combine all available seasons into one ranked list, tagging each
    player with their season year and giving them a synthetic cross-year
    id (`<year>-<id>`) so the template can distinguish identical IDs from
    different scrapes.

    Not cached at the combined level — available_years() may grow while
    a background scrape is running, and we want each request to pick up
    any newly-finished seasons. The per-year cache makes the combine cheap.
    """
    combined: list[dict] = []
    profiles: dict = {}

    # Current season first (curated list applied per-season when present;
    # no stub rows — score-less entries can't rank on a cross-year board)
    cur_pool, _, _ = board_filter(PLAYERS, CURRENT_SEASON_YEAR, with_stubs=False)
    for p in cur_pool:
        clone = dict(p)
        clone["_season_year"] = CURRENT_SEASON_YEAR
        clone["_xkey"] = f"{CURRENT_SEASON_YEAR}-{p['id']}"
        combined.append(clone)
        profiles[clone["_xkey"]] = PROFILES.get(p["id"], get_profile(p))

    # Then each historical year
    for y, _label, _is_cur in available_years():
        if y == CURRENT_SEASON_YEAR:
            continue
        players, _season = _load_history_year(y)
        if players is None:
            continue
        pool, _, _ = board_filter(players, y, with_stubs=False)
        for p in pool:
            clone = dict(p)
            clone["_season_year"] = y
            clone["_xkey"] = f"{y}-{p['id']}"
            combined.append(clone)
            profiles[clone["_xkey"]] = get_profile(p)

    combined.sort(key=lambda p: p.get("draft_score", 0), reverse=True)
    for i, p in enumerate(combined):
        p["rank"] = i + 1
        # The template keys profiles by p["id"]; remap so it finds them.
        p["id"] = p["_xkey"]

    return combined, profiles, "All Years"


# ── Curated big-board lists (optional, one per season) ───────────────────────
# datasets/board_lists/board_<year>.txt: one player per line as "Name" or
# "Name | School", '#' comments allowed. When a season's file exists, its big
# board shows ONLY those players (still ordered by draft score). Names that
# match no NCAA record (internationals, G-League, typos) are reported back so
# they're never silently dropped.

def _load_board_list(year, players):
    """Return (set_of_ids, unmatched_names) for a season's curated list,
    or (None, []) when no list file exists for that year."""
    path = BOARD_LISTS_DIR / f"board_{year}.txt"
    if not path.exists():
        return None, []
    by_norm: dict = {}
    by_initial: dict = {}
    for p in players:
        full, initial = name_keys(p["name"])
        by_norm.setdefault(full, []).append(p)
        by_initial.setdefault(initial, []).append(p)

    def _school_scope(cands, school):
        sc = normalize_name(school)
        scoped = [p for p in cands
                  if sc in normalize_name(p.get("school", ""))
                  or normalize_name(p.get("school", "")) in sc]
        return scoped or cands

    ids, unmatched = set(), []
    mock_rank = 0  # the list's line order IS the consensus mock ranking
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.split("#")[0].strip()
        if not line:
            continue
        mock_rank += 1
        name, _, school = (s.strip() for s in line.partition("|"))
        cands = by_norm.get(normalize_name(name), [])
        if not cands:  # nickname-tolerant fallback: first initial + last name
            _, initial = name_keys(name)
            cands = by_initial.get(initial, [])
        if len(cands) > 1 and school:
            cands = _school_scope(cands, school)
        if cands:
            # if still ambiguous, take the most prominent (best-ranked) match
            best = min(cands, key=lambda p: p["rank"])
            best["_mock_rank"] = mock_rank
            ids.add(best["id"])
        else:
            unmatched.append((name, school, mock_rank))
    return ids, unmatched


# Draft outcomes per year (for stub rows): {norm_name: {pick, tier}} or None
# when that year's draft hasn't happened / wasn't scraped.
_OUTCOME_CACHE: dict = {}


def _outcome_lookup(year):
    if year not in _OUTCOME_CACHE:
        path = HISTORY_DIR / f"draft_results_{year}.json"
        if not path.exists():
            _OUTCOME_CACHE[year] = None
        else:
            table = {}
            for pick in json.loads(path.read_text(encoding="utf-8")).get("picks", []):
                table[normalize_name(pick.get("player", ""))] = {
                    "pick": pick.get("pick_overall"),
                    "tier": pick.get("career_tier"),
                    # Tier thresholds are calibrated for 2-5 year careers; a
                    # 2024-25 draftee's "rotation" label says nothing yet.
                    "mature": year in MATURE_DRAFT_YEARS,
                }
            _OUTCOME_CACHE[year] = table
    return _OUTCOME_CACHE[year]


# Scraped international/G-League pre-draft stats (datasets/intl/intl_<year>.json)
_INTL_CACHE: dict = {}


def _intl_lookup(year):
    if year not in _INTL_CACHE:
        path = INTL_DIR / f"intl_{year}.json"
        table = {}
        if path.exists():
            for r in json.loads(path.read_text(encoding="utf-8")).get("players", []):
                table[r.get("norm_name") or normalize_name(r["name"])] = r
        _INTL_CACHE[year] = table
    return _INTL_CACHE[year]


def _make_stub(name: str, club: str, year, idx: int, mock_rank=None) -> dict:
    """Board row for a listed prospect with no NCAA record (international,
    G-League, OTE, or injured/never played). Enriched with scraped intl stats
    and the real draft outcome when we have them. rank pushes stubs below all
    NCAA players; id is synthetic-negative so it can't collide."""
    intl = _intl_lookup(year).get(normalize_name(name)) or {}
    stub = {
        "id": -(idx + 1),
        "rank": 100000 + idx,
        "name": name,
        "pos": intl.get("pos") or "—",
        "school": intl.get("team") or club or "—",
        "conference": intl.get("league", ""),
        "year": intl.get("age_label") or "No NCAA",
        "height": intl.get("height") or "—",
        "stats": intl.get("stats") or {},
        "advanced": {},
        "draft_score": 0.0,
        "_intl_stub": True,
        "_mock_rank": mock_rank,
    }
    outcomes = _outcome_lookup(year)
    if outcomes is not None:
        stub["_draft_complete"] = True
        nba = outcomes.get(normalize_name(name))
        if nba:
            stub["nba"] = nba
    return stub


_BOARD_CACHE: dict = {}


def board_filter(players: list[dict], year, with_stubs: bool = True):
    """Apply a season's curated list to its players. Returns
    (players_plus_stub_rows, unmatched_names, is_curated)."""
    if year == "all" or year is None:
        return players, [], False
    if year not in _BOARD_CACHE:
        _BOARD_CACHE[year] = _load_board_list(year, players)
    ids, unmatched = _BOARD_CACHE[year]
    if ids is None:
        return players, [], False
    pool = [p for p in players if p["id"] in ids]
    if with_stubs:
        pool += [_make_stub(n, club, year, i, mock_rank=mr)
                 for i, (n, club, mr) in enumerate(unmatched)]
    return pool, [n for n, _, _ in unmatched], True


# ── Raw college production score ─────────────────────────────────────────────
# The SAME college-stat components as the draft score, but with the
# conference / age / position multipliers neutralized (damp=0 -> mult 1.0)
# and the HS recruit-pedigree bonus removed. Pure "what did he produce in
# college" — the un-adjusted view of the main ranking.
_RAW_WEIGHTS = dict(DEFAULT_WEIGHTS, recruit=0.0,
                    age_damp=0.0, conf_damp=0.0, pos_damp=0.0)
_RAW_CACHE: dict = {}


def raw_score(p: dict):
    """Raw college production score (None for non-NCAA stub rows)."""
    if p.get("_intl_stub"):
        return None
    key = p["id"]
    if key not in _RAW_CACHE:
        parts = draft_score(p, return_parts=True)
        _RAW_CACHE[key] = round(combine_parts(parts, _RAW_WEIGHTS), 1)
    return _RAW_CACHE[key]


# ── Percentiles (pre-sorted once at import) ───────────────────────────────────

_PCTL_STATS = ["PPG", "RPG", "APG", "SPG", "BPG", "FG%", "3P%", "FT%", "MPG"]
_PCTL_ADV = ["PER", "TS%", "eFG%", "USG%", "BPM", "Win Shares", "WS/40"]
_PCTL_KEYS = _PCTL_STATS + _PCTL_ADV


def _build_percentiles():
    sorted_vals = {}
    for key in _PCTL_KEYS:
        vals = []
        for p in PLAYERS:
            src = p["stats"] if key in _PCTL_STATS else p.get("advanced", {})
            v = src.get(key)
            if v is not None:
                vals.append(v)
        vals.sort()
        sorted_vals[key] = vals
    return sorted_vals


_SORTED_STATS = _build_percentiles()


def get_percentiles(player: dict) -> dict:
    """Return {stat_key: percentile_int} for a player."""
    result = {}
    for key in _PCTL_KEYS:
        src = player["stats"] if key in _PCTL_STATS else player.get("advanced", {})
        v = src.get(key)
        vals = _SORTED_STATS.get(key, [])
        if v is not None and vals:
            idx = bisect_left(vals, v)
            result[key] = int(round(idx / len(vals) * 100))
        else:
            result[key] = None
    return result
