"""Page routes. Routes never mutate the shared store — view copies only."""

from flask import Blueprint, redirect, render_template, request, url_for

from model.archetypes import (DEFAULT_WEIGHTS, _CLASS_BONUS, _CONF_MULTIPLIER,
                              _POS_VALUE, draft_score)
from model.strengths import ALL_RECIPES, OFFENSE_RECIPES
from web import store
from web.charts import fmt_stat, make_radar_json
from web.content import (ARCHETYPE_DESCRIPTIONS, SCORE_COMPONENT_KEYS,
                         SCORE_COMPONENTS, SCORE_METHODOLOGY, TIER_LABELS)
from web.db import (get_all_boards, get_board_order, get_db,
                    get_notes_map, get_watchlist_ids)

views_bp = Blueprint("views", __name__)


@views_bp.route("/")
def index():
    import json as _json

    from core.config import DATASETS_DIR
    _, _, season_label = store.get_year_data(store.CURRENT_SEASON_YEAR)
    players, _, _ = store.board_filter(store.PLAYERS, store.CURRENT_SEASON_YEAR,
                                       with_stubs=True)
    rho = 0.0
    mpath = DATASETS_DIR / "strengths_model.json"
    if mpath.exists():
        rho = (_json.loads(mpath.read_text(encoding="utf-8"))
               .get("validation", {}).get("loyo_spearman_model", 0.0))
    return render_template("home.html", n_prospects=len(players),
                           season_label=season_label, model_rho=rho)


@views_bp.route("/scouting")
def scouting():
    pid = request.args.get("player_id", type=int)
    year_q = request.args.get("year", type=int)
    is_hist = year_q and year_q != store.CURRENT_SEASON_YEAR
    player = None
    if pid and is_hist:
        hist_players, hist_profiles, _ = store.get_year_data(year_q)
        if hist_players is not None:
            if pid < 0:
                player = store.get_stub(pid, year_q)
            else:
                player = next((p for p in hist_players if p["id"] == pid), None)
    elif pid and pid in store.PLAYERS_BY_ID:
        player = store.PLAYERS_BY_ID[pid]
    elif pid and pid < 0:  # no-NCAA stub (international / G-League / injured)
        player = store.get_stub(pid)
    if player is None:
        player = store.PLAYERS[0] if store.PLAYERS else None

    if not player:
        return "No player data loaded.", 500

    profile = store.PROFILES.get(player["id"]) or store.get_profile(player)
    wl_ids = get_watchlist_ids()
    notes = get_notes_map()
    percentiles = store.get_percentiles(player)

    # Compare player (optional)
    cmp_id = request.args.get("compare", type=int)
    cmp_player = store.PLAYERS_BY_ID.get(cmp_id) if cmp_id else None
    cmp_profile = store.PROFILES.get(cmp_id, {}) if cmp_player else None
    cmp_percentiles = store.get_percentiles(cmp_player) if cmp_player else None

    radar_json = (make_radar_json(player, cmp_player) if cmp_player
                  else make_radar_json(player))

    # Player search list (top 200 for dropdown)
    search_players = sorted(store.PLAYERS, key=lambda p: p["rank"])[:200]

    return render_template("scouting.html",
        player=player, profile=profile, radar_json=radar_json,
        in_watchlist=player["id"] in wl_ids,
        note=notes.get(player["id"], ""),
        search_players=search_players,
        all_players=store.PLAYERS,
        fmt_stat=fmt_stat,
        tier_labels=TIER_LABELS,
        arch_desc=ARCHETYPE_DESCRIPTIONS,
        percentiles=percentiles,
        cmp_player=cmp_player, cmp_profile=cmp_profile,
        cmp_percentiles=cmp_percentiles,
    )


@views_bp.route("/compare")
def compare():
    ids = request.args.get("ids", "")
    selected = []
    if ids:
        for sid in ids.split(","):
            try:
                pid = int(sid.strip())
                if pid in store.PLAYERS_BY_ID:
                    selected.append(store.PLAYERS_BY_ID[pid])
            except ValueError:
                pass

    radar_json = make_radar_json(*selected) if selected else "{}"

    # Build comparison stats
    _lower_better = {"TOV", "TOV%", "PF"}
    stat_keys = ["PPG", "RPG", "APG", "SPG", "BPG", "FG%", "3P%", "FT%",
                 "MPG", "TOV", "PER", "TS%", "eFG%", "USG%", "BPM", "Win Shares"]
    comp_rows = []
    for key in stat_keys:
        row = {"stat": key, "cells": []}
        vals = []
        for p in selected:
            v = p["stats"].get(key) if key in p["stats"] else p["advanced"].get(key)
            vals.append(v)
            row["cells"].append(fmt_stat(v, key))
        numeric = [(i, v) for i, v in enumerate(vals) if v is not None and v != 0]
        best_idx = None
        if numeric:
            if key in _lower_better:
                best_idx = min(numeric, key=lambda x: x[1])[0]
            else:
                best_idx = max(numeric, key=lambda x: x[1])[0]
        row["best_idx"] = best_idx
        comp_rows.append(row)

    search_players = sorted(store.PLAYERS, key=lambda p: p["rank"])[:200]

    return render_template("compare.html",
        selected=selected, radar_json=radar_json,
        comp_rows=comp_rows, search_players=search_players,
        profiles=store.PROFILES, fmt_stat=fmt_stat,
    )


@views_bp.route("/bigboard")
def bigboard():
    # Which season are we viewing? Accept "all" or an int year.
    year_q = request.args.get("year", default="")
    if year_q == "all":
        year = "all"
    elif year_q.isdigit():
        year = int(year_q)
    else:
        year = store.CURRENT_SEASON_YEAR

    players, profiles, season_label = store.get_year_data(year)
    if players is None:
        year = store.CURRENT_SEASON_YEAR
        players, profiles, season_label = store.get_year_data(year)

    # "Historical" means anything that isn't the live current season —
    # disables manual draft toggle, watchlist, custom boards.
    is_historical = year != store.CURRENT_SEASON_YEAR

    # Curated list filter: when datasets/board_lists/board_<year>.txt exists,
    # the board shows ONLY those players (still draft-score order).
    pool, unmatched_names, is_curated = store.board_filter(players, year)

    # Sort mode: the adjusted draft score (default) or the RAW college
    # production score (same components, no conference/age/position
    # multipliers, no HS recruit bonus).
    # Default order: the strengths model when this class has one (it beat the
    # formula 3x held-out, so it IS the ranking); the formula stays one click
    # away on the toggle.
    has_model = any(p.get("sm_score") is not None for p in pool)
    has_outcomes = any((p.get("nba") or {}).get("value") is not None for p in pool)
    sort_mode = request.args.get("sort") or ("model" if has_model else "score")
    if sort_mode == "nba" and has_outcomes:
        # Rank by what players ACTUALLY became: career TIER first (tiers carry
        # the WS/48 quality floors raw value ignores — Keyonte George problem),
        # then value within tier. Tier-first also keeps young classes honest on
        # the all-years board: their values are within-class percentiles and
        # can't be compared raw against the pooled mature scale (a 1.00 from a
        # 2-season career must not outrank Anthony Edwards).
        _tier_rank = {"star": 4, "starter": 3, "rotation": 2, "bench": 1,
                      "no_nba": 0}

        def _nba_key(p):
            nba = p.get("nba") or {}
            if nba.get("value") is None:
                return (-1, -1e9)
            return (_tier_rank.get(nba.get("tier"), 0), nba["value"])

        pool = sorted(pool, key=_nba_key, reverse=True)
    elif sort_mode == "raw":
        pool = sorted(pool, key=lambda p: -(store.raw_score(p) or -1e9))
    elif sort_mode == "stats" and has_model:
        # the model with the market column zeroed: production only, no draft
        # buzz — the board the model would publish if mocks didn't exist
        pool = sorted(pool, key=lambda p: -(p.get("_sm_stats_score")
                                            if p.get("_sm_stats_score") is not None else -1e9))
    elif sort_mode == "model" and has_model:
        # sm_score (projected NBA value) sorts within a class identically to
        # sm_rank AND compares across classes on the all-years board
        pool = sorted(pool, key=lambda p: -(p.get("sm_score")
                                            if p.get("sm_score") is not None else -1e9))
    else:
        sort_mode = "score"
        pool = sorted(pool, key=lambda p: p["rank"])

    # Shallow-copy into view dicts: routes run on Flask's threaded server and
    # must never mutate the shared global player objects (display position,
    # board order, etc. are per-request, per-board state).
    top200 = [dict(p) for p in pool[:200]]
    for p in top200:
        p["_raw"] = store.raw_score(p)
    # Watchlist + manual draft toggles only apply to the current season —
    # historical player IDs reference different people each year.
    wl_ids = get_watchlist_ids() if not is_historical else set()
    boards = get_all_boards() if not is_historical else []

    # Custom boards (with manual ordering) only make sense for current season
    board_id = request.args.get("board_id", type=int) if not is_historical else None
    current_board = None
    is_master = board_id is None

    if board_id is not None:
        row = get_db().execute(
            "SELECT id, name FROM boards WHERE id=?", (board_id,)).fetchone()
        if row:
            current_board = dict(row)
        else:
            is_master = True
            board_id = None

    if not is_master:
        board_order = get_board_order(board_id)
        for p in top200:
            p["_board_pos"] = board_order.get(p["id"], p["rank"])
        top200.sort(key=lambda p: p["_board_pos"])

    for i, p in enumerate(top200):
        p["_display_pos"] = i + 1

    return render_template("bigboard.html",
        players=top200, wl_ids=wl_ids,
        tier_labels=TIER_LABELS, profiles=profiles,
        fmt_stat=fmt_stat,
        boards=boards, current_board=current_board,
        is_master=is_master, board_id=board_id,
        available_years=store.available_years(), current_year=year,
        season_label=season_label, is_historical=is_historical,
        is_curated=is_curated, unmatched_names=unmatched_names,
        sort_mode=sort_mode, has_outcomes=has_outcomes,
    )


@views_bp.route("/watchlist")
def watchlist():
    wl_ids = get_watchlist_ids()
    notes = get_notes_map()
    watched = [store.PLAYERS_BY_ID[pid] for pid in wl_ids if pid in store.PLAYERS_BY_ID]
    watched.sort(key=lambda p: p["rank"])

    return render_template("watchlist.html",
        players=watched, notes=notes, profiles=store.PROFILES,
        tier_labels=TIER_LABELS, fmt_stat=fmt_stat,
    )


@views_bp.route("/scarcity")
def scarcity():
    """Class depth report, computed live from the fit engine: how many
    players in this class can actually play each role, and how steep the
    drop-off is after the top guys."""
    year_q = request.args.get("year", default="")
    year = int(year_q) if year_q.isdigit() else store.CURRENT_SEASON_YEAR
    players, _, season_label = store.get_year_data(year)
    if players is None:
        year = store.CURRENT_SEASON_YEAR
        players, _, season_label = store.get_year_data(year)
    store.ensure_fits(year, players)
    pool, _, _ = store.board_filter(players, year, with_stubs=False)

    rows = []
    for name in ALL_RECIPES:
        members = sorted((p for p in pool if name in (p.get("fits") or {})),
                         key=lambda p: -p["fits"][name])
        if not members:
            continue
        elite = [p for p in members if p["fits"][name] >= 80]
        solid = [p for p in members if 55 <= p["fits"][name] < 80]
        # Drop-off: fit gap between the #1 and #4 player in the role
        dropoff = (members[0]["fits"][name] - members[3]["fits"][name]
                   if len(members) >= 4 else 0)
        if len(elite) <= 2:
            signal = "Very scarce"
        elif len(elite) <= 4:
            signal = "Scarce"
        elif len(elite) <= 8:
            signal = "Moderate"
        else:
            signal = "Deep"
        rows.append({
            "name": name,
            "side": "offensive" if name in OFFENSE_RECIPES else "defensive",
            "n_elite": len(elite), "n_solid": len(solid),
            "top": members[:3], "dropoff": dropoff, "signal": signal,
        })
    rows.sort(key=lambda r: (r["n_elite"], r["n_solid"]))

    return render_template("scarcity.html",
        rows=rows, arch_desc=ARCHETYPE_DESCRIPTIONS,
        available_years=store.available_years(), current_year=year,
        season_label=season_label,
    )


@views_bp.route("/needs")
def needs():
    """Fit-based: pick the roles your team is missing, get the class ranked
    by MEASURED fit for exactly those roles (mean of the selected archetype
    fit percentiles; position-ineligible counts as 0 for that need)."""
    from model.strengths import DEFENSE_RECIPES
    pool, _, _ = store.board_filter(store.PLAYERS, store.CURRENT_SEASON_YEAR,
                                    with_stubs=False)
    off_archetypes = [n for n in OFFENSE_RECIPES]
    def_archetypes = [n for n in DEFENSE_RECIPES]

    sel_off = request.args.getlist("off")
    sel_def = request.args.getlist("def")
    sel = [a for a in sel_off + sel_def if a in ALL_RECIPES]

    results = []
    if sel:
        for p in pool:
            fits = p.get("fits") or {}
            need_fits = {a: fits.get(a) for a in sel}
            have = [v for v in need_fits.values() if v is not None]
            if not have:
                continue
            fit_avg = sum(v or 0 for v in need_fits.values()) / len(sel)
            results.append({
                "player": p,
                "need_fits": need_fits,
                "fit_avg": round(fit_avg),
            })
        results.sort(key=lambda r: -r["fit_avg"])
        results = results[:50]

    return render_template("needs.html",
        off_archetypes=off_archetypes, def_archetypes=def_archetypes,
        sel_off=sel_off, sel_def=sel_def, sel=sel,
        results=results, fmt_stat=fmt_stat,
        arch_desc=ARCHETYPE_DESCRIPTIONS,
    )


@views_bp.route("/archetypes")
def archetypes():
    """Ranked leaderboards: every player in the class scored on every
    applicable archetype, percentiled within the class. Descriptive only —
    these never feed the draft score."""
    year_q = request.args.get("year", default="")
    year = int(year_q) if year_q.isdigit() else store.CURRENT_SEASON_YEAR
    players, _, season_label = store.get_year_data(year)
    if players is None:
        year = store.CURRENT_SEASON_YEAR
        players, _, season_label = store.get_year_data(year)
    store.ensure_fits(year, players)
    pool, _, _ = store.board_filter(players, year, with_stubs=False)

    # Detail view: one archetype, EVERY eligible player, with the component
    # strengths the recipe is built from.
    selected = request.args.get("arch", "")
    detail = None
    if selected in ALL_RECIPES:
        _, recipe, _ = ALL_RECIPES[selected]
        components = [(k.replace("@abs", ""), k.endswith("@abs"), w)
                      for k, w in sorted(recipe.items(), key=lambda kv: -kv[1])]
        members = sorted((p for p in pool if selected in (p.get("fits") or {})),
                         key=lambda p: -p["fits"][selected])
        detail = {
            "name": selected,
            "side": "offensive" if selected in OFFENSE_RECIPES else "defensive",
            "components": components,
            "members": members,
        }

    groups = []
    for name in ALL_RECIPES:
        members = sorted((p for p in pool if name in (p.get("fits") or {})),
                         key=lambda p: -p["fits"][name])
        if members:
            groups.append({
                "name": name,
                "side": "offensive" if name in OFFENSE_RECIPES else "defensive",
                "members": members[:15],
                "total": len(members),
                "n_primary": sum(1 for p in pool
                                 if p.get("archetype") == name
                                 or p.get("defensive_archetype") == name),
            })

    return render_template("archetypes.html",
        groups=groups, detail=detail, all_archetypes=list(ALL_RECIPES),
        arch_desc=ARCHETYPE_DESCRIPTIONS,
        available_years=store.available_years(), current_year=year,
        season_label=season_label,
    )


@views_bp.route("/ranking")
def ranking():
    """Explains the ACTUAL ranking: the strengths model, straight from the
    persisted model file so this page can never drift from the math."""
    import json as _json
    from core.config import DATASETS_DIR
    path = DATASETS_DIR / "strengths_model.json"
    model = _json.loads(path.read_text(encoding="utf-8")) if path.exists() else None
    coefs = []
    if model:
        coefs = sorted(zip(model["features"], model["coef"]),
                       key=lambda t: -abs(t[1]))
    return render_template("ranking.html", model=model, coefs=coefs)


@views_bp.route("/mockdraft")
def mockdraft():
    import json as _json
    all_players, _, season_label = store.get_year_data(store.CURRENT_SEASON_YEAR)
    pool, _, _ = store.board_filter(all_players, store.CURRENT_SEASON_YEAR,
                                    with_stubs=True)
    players = []
    for p in sorted(pool, key=lambda q: (q.get("sm_score") is None,
                                         -(q.get("sm_score") or 0))):
        pred = p.get("pred") or {}
        franks = p.get("fit_ranks") or {}
        best = min(franks.items(), key=lambda t: t[1][0]) if franks else None
        players.append({
            "id": p["id"], "name": p["name"], "pos": p.get("pos", ""),
            "school": p.get("school", ""),
            "smRank": p.get("sm_rank"), "mock": p.get("_mock_rank"),
            "boom": round(pred["success"] * 100) if pred.get("success") is not None else None,
            "bust": round(pred["bust"] * 100) if pred.get("bust") is not None else None,
            "arch": f"{best[0]} #{best[1][0]}" if best else p.get("archetype", ""),
        })
    from core.config import DATASETS_DIR
    order = []
    opath = DATASETS_DIR / f"draft_order_{store.CURRENT_SEASON_YEAR}.json"
    if opath.exists():
        order = _json.loads(opath.read_text(encoding="utf-8")).get("picks", [])
    return render_template("mockdraft.html", active_page="mockdraft",
                           pool_json=_json.dumps(players),
                           order_json=_json.dumps(order),
                           season_label=season_label)
