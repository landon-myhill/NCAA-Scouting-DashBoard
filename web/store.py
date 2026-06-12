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
from model.strengths import compute_fits, compute_strengths

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
                          "value": pick.get("nba_value"),
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
    # No live classify() fallback — legacy heuristic labels are retired.
    # Pool players carry v2 badges; everyone else just shows tags/red flags.
    return {
        "primary": p.get("archetype", ""),
        "defensive": p.get("defensive_archetype", ""),
        "all_offensive": p.get("all_offensive", []),
        "all_defensive": p.get("all_defensive", []),
        "tags": p.get("tags", []),
        "red_flags": p.get("red_flags", []),
    }


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
    ensure_fits(year, players)  # class-relative strengths/fits + v2 badges
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

    # Current season first. Stubs included — graded internationals (Wemby!)
    # carry sm_score and rank inline; score-less ones sink to the bottom.
    cur_pool, _, _ = board_filter(PLAYERS, CURRENT_SEASON_YEAR)
    for p in cur_pool:
        clone = dict(p)
        clone["_season_year"] = CURRENT_SEASON_YEAR
        clone["_xkey"] = f"{CURRENT_SEASON_YEAR}-{p['id']}"
        combined.append(clone)
        profiles[clone["_xkey"]] = PROFILES.get(p["id"], get_profile(p))

    # Then each historical year — via get_year_data so each class's pool has
    # its strengths/fits/model scores stamped (and is cached) before cloning
    for y, _label, _is_cur in available_years():
        if y == CURRENT_SEASON_YEAR:
            continue
        players, _profiles, _season = get_year_data(y)
        if players is None:
            continue
        pool, _, _ = board_filter(players, y)
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
        # Keep the original id so Scout links can resolve the real player.
        p["_orig_id"] = p["id"]
        p["id"] = p["_xkey"]

    return combined, profiles, "All Years"


# ── Curated big-board lists (optional, one per season) ───────────────────────
# datasets/board_lists/board_<year>.txt: one player per line as "Name" or
# "Name | School", '#' comments allowed. When a season's file exists, its big
# board shows ONLY those players (still ordered by draft score). Names that
# match no NCAA record (internationals, G-League, typos) are reported back so
# they're never silently dropped.

def _load_board_list(year, players):
    from model.boards import load_board
    return load_board(year, players)


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
                    "value": pick.get("nba_value"),  # position-relative career value
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
        # Hand-curated entries (OTE etc. — leagues no scrapeable site covers)
        manual = INTL_DIR / "intl_manual.json"
        if manual.exists():
            for r in json.loads(manual.read_text(encoding="utf-8")).get(str(year), []):
                table[r.get("norm_name") or normalize_name(r["name"])] = r
        _INTL_CACHE[year] = table
    return _INTL_CACHE[year]


_INTL_MODEL = None


def _intl_grade(intl_rec: dict, mock_rank, year):
    """Grade a no-NCAA prospect with the experimental international model
    (analytics.intl_model) — same 0-1 value scale as sm_score, so they slot
    into the board order. Returns None when there's nothing to grade."""
    global _INTL_MODEL
    if not intl_rec or not intl_rec.get("stats"):
        return None
    if _INTL_MODEL is None:
        from core.config import DATASETS_DIR
        path = DATASETS_DIR / "intl_model.json"
        _INTL_MODEL = json.loads(path.read_text(encoding="utf-8")) if path.exists() else False
    if not _INTL_MODEL:
        return None
    import numpy as np
    from analytics.intl_model import featurize
    rec = dict(intl_rec)
    rec["_draft_year"] = year if isinstance(year, int) else CURRENT_SEASON_YEAR
    m = _INTL_MODEL
    x = np.array(featurize(rec, mock_rank), float)
    med = np.array(m["med"])
    x[np.isnan(x)] = med[np.isnan(x)]
    stat = float((x - np.array(m["mu"])) / np.array(m["sd"]) @ np.array(m["coef"]) + m["y0"])
    # Blend with the pick-value curve at the validation-chosen weight — for
    # internationals the market screen carries info our thin stats can't.
    alpha = m.get("alpha", 1.0)
    if mock_rank and "curve_a" in m:
        import math
        curve = m["curve_a"] + m["curve_b"] * math.log(min(max(mock_rank, 1), 61))
        return alpha * stat + (1 - alpha) * curve
    return stat


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
    grade = _intl_grade(intl, mock_rank, year)
    if grade is not None:
        stub["sm_score"] = round(grade, 4)  # slots into board order inline
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


_FITS_DONE: set = set()


def ensure_fits(year, players: list[dict]) -> None:
    """Compute strengths + archetype fits for a season's draft pool, once.
    Percentiles are relative to THAT class only (the eligibility rule).
    Load-time enrichment of the shared dicts, like the NBA outcome badges —
    these numbers NEVER feed the draft score."""
    if year in _FITS_DONE or year == "all" or year is None:
        return
    _FITS_DONE.add(year)
    pool, _, curated = board_filter(players, year, with_stubs=False)
    if not curated:
        return
    pool = sorted(pool, key=lambda p: p["rank"])
    compute_strengths(pool, reference=pool)
    compute_fits(pool, reference=pool)
    _stamp_model_rank(pool)


def _stamp_model_rank(pool: list[dict]) -> None:
    """Score the pool with the trained strengths model (datasets/
    strengths_model.json, trained+validated in analytics.strengths_model)
    and stamp sm_score / sm_rank. The model learned its own age and height
    adjusters from the eligible 2020-23 populations."""
    from core.config import DATASETS_DIR
    path = DATASETS_DIR / "strengths_model.json"
    if not path.exists() or not pool:
        return
    import numpy as np
    from analytics.strengths_model import featurize
    m = json.loads(path.read_text(encoding="utf-8"))
    feats = m["features"]
    X = np.array([featurize(p, feats) for p in pool], float)
    idx = np.where(np.isnan(X))
    X[idx] = np.take(np.array(m["med"]), idx[1])
    mu, sd, coef = np.array(m["mu"]), np.array(m["sd"]), np.array(m["coef"])
    Z = (X - mu) / sd
    pred = Z @ coef + m["y0"]
    # Stat-support: the same model with the market column's contribution
    # zeroed — where his STATS alone put him. A big gap between sm_rank and
    # sm_stats_rank means the rank is borrowed from the market (the Fears/
    # Okoro warning); stats-rank above model-rank is the model's own
    # conviction (the Cole Anthony shape).
    pred_stats = pred.copy()
    if "market" in feats:
        mi = feats.index("market")
        pred_stats = pred - Z[:, mi] * coef[mi]
    bands = m.get("rank_bands", {})
    for p, v, vs in zip(pool, pred, pred_stats):
        p["sm_score"] = round(float(v), 4)
        p["_sm_stats_score"] = float(vs)
        band = bands.get(str(p["id"]))
        if band:
            p["sm_band"] = band  # [5th, 95th] percentile rank across bootstraps
    for i, p in enumerate(sorted(pool, key=lambda p: -p["sm_score"]), 1):
        p["sm_rank"] = i
    for i, p in enumerate(sorted(pool, key=lambda p: -p["_sm_stats_score"]), 1):
        p["sm_stats_rank"] = i


def get_stub(pid, year=None):
    """Resolve a no-NCAA stub (negative id) from a class pool, so every
    listed prospect — international, G-League, injured — has a scouting
    card built from whatever data we hold on them."""
    year = year or CURRENT_SEASON_YEAR
    if year == CURRENT_SEASON_YEAR:
        players = PLAYERS
    else:
        players, _, _ = get_year_data(year)
        if players is None:
            return None
    pool, _, _ = board_filter(players, year)
    for p in pool:
        if p.get("_intl_stub") and p["id"] == pid:
            return p
    return None


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


# ── Startup enrichment ───────────────────────────────────────────────────────
# Strengths/fits for the current class, then refresh the affected profiles
# (their archetype badges now come from the fit engine).
ensure_fits(CURRENT_SEASON_YEAR, PLAYERS)
PROFILES.update({p["id"]: get_profile(p) for p in PLAYERS if p.get("fits")})
