"""Page routes. Routes never mutate the shared store — view copies only."""

from flask import Blueprint, redirect, render_template, request, url_for

from model.archetypes import (DEFAULT_WEIGHTS, _CLASS_BONUS, _CONF_MULTIPLIER,
                              _POS_VALUE, draft_score)
from web import store
from web.charts import fmt_stat, make_radar_json
from web.content import (ARCHETYPE_DESCRIPTIONS, SCORE_COMPONENT_KEYS,
                         SCORE_COMPONENTS, SCORE_METHODOLOGY, TIER_LABELS)
from web.db import (get_all_boards, get_board_order, get_db,
                    get_notes_map, get_watchlist_ids)

views_bp = Blueprint("views", __name__)


@views_bp.route("/")
def index():
    return redirect(url_for("views.scouting"))


@views_bp.route("/scouting")
def scouting():
    pid = request.args.get("player_id", type=int)
    if pid and pid in store.PLAYERS_BY_ID:
        player = store.PLAYERS_BY_ID[pid]
    else:
        player = store.PLAYERS[0] if store.PLAYERS else None

    if not player:
        return "No player data loaded.", 500

    profile = store.PROFILES.get(player["id"], {})
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
    sort_mode = request.args.get("sort", "score")
    if sort_mode == "raw":
        pool = sorted(pool, key=lambda p: -(store.raw_score(p) or -1e9))
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
        sort_mode=sort_mode,
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
    return render_template("scarcity.html",
        scarcity=store.SCARCITY, arch_desc=ARCHETYPE_DESCRIPTIONS,
        tier_labels=TIER_LABELS,
    )


@views_bp.route("/needs")
def needs():
    # Build list of all archetypes that exist in the top 200
    top200 = sorted(store.PLAYERS, key=lambda p: p["rank"])[:200]
    off_archetypes = sorted(set(
        a for p in top200
        for a in store.PROFILES.get(p["id"], {}).get("all_offensive", []) if a
    ))
    def_archetypes = sorted(set(
        a for p in top200
        for a in store.PROFILES.get(p["id"], {}).get("all_defensive", []) if a
    ))

    sel_off = request.args.getlist("off")
    sel_def = request.args.getlist("def")

    results = []
    if sel_off or sel_def:
        for p in top200:
            prof = store.PROFILES.get(p["id"], {})
            p_off = set(prof.get("all_offensive", []))
            p_def = set(prof.get("all_defensive", []))

            off_matches = [a for a in sel_off if a in p_off]
            def_matches = [a for a in sel_def if a in p_def]
            total_matches = len(off_matches) + len(def_matches)
            total_needs = len(sel_off) + len(sel_def)

            if total_matches > 0:
                results.append({
                    "player": p,
                    "profile": prof,
                    "off_matches": off_matches,
                    "def_matches": def_matches,
                    "total_matches": total_matches,
                    "total_needs": total_needs,
                    "fit_pct": round(total_matches / total_needs * 100) if total_needs else 0,
                })

        results.sort(key=lambda r: (-r["total_matches"], -r["player"].get("draft_score", 0)))

    return render_template("needs.html",
        off_archetypes=off_archetypes, def_archetypes=def_archetypes,
        sel_off=sel_off, sel_def=sel_def,
        results=results, profiles=store.PROFILES,
        tier_labels=TIER_LABELS, fmt_stat=fmt_stat,
        arch_desc=ARCHETYPE_DESCRIPTIONS,
    )


@views_bp.route("/ranking")
def ranking():
    # Single source of truth: the live formula. We score each example with the
    # SAME draft_score()/combine_parts()/DEFAULT_WEIGHTS the board uses, via the
    # return_parts decomposition — no re-implemented math that can drift.
    examples = []
    top10 = sorted(store.PLAYERS, key=lambda p: p["rank"])[:10]
    for p in top10:
        parts = draft_score(p, return_parts=True)
        w = DEFAULT_WEIGHTS
        # Weighted contribution of each additive component (tov is a penalty).
        contrib = {k: parts[k] * w[k] for k in SCORE_COMPONENT_KEYS}
        contrib["tov"] = -parts["tov"] * w["tov"]
        raw = sum(contrib.values())
        mult = (parts["age_mult"] * parts["conf_mult"] * parts["pos_mult"])
        examples.append({
            "id": p["id"], "rank": p["rank"], "name": p["name"],
            "pos": p.get("pos", ""), "school": p["school"],
            "year": p.get("year", "Unknown"), "conf": p.get("conference", ""),
            "contrib": contrib, "raw": raw, "mult": round(mult, 3),
            "final": round(p.get("draft_score", 0), 1),
        })

    class_bonuses = sorted(_CLASS_BONUS.items(), key=lambda x: x[1], reverse=True)
    conf_multipliers = sorted(_CONF_MULTIPLIER.items(), key=lambda x: x[1], reverse=True)
    pos_values = sorted(_POS_VALUE.items(), key=lambda x: x[1], reverse=True)

    return render_template("ranking.html",
        components=SCORE_COMPONENTS, weights=DEFAULT_WEIGHTS,
        examples=examples, methodology=SCORE_METHODOLOGY,
        class_bonuses=class_bonuses,
        conf_multipliers=conf_multipliers,
        pos_values=pos_values,
    )
