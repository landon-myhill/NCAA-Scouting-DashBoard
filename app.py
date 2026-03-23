#!/usr/bin/env python3
"""
NCAA Scouting Dashboard — Flask Application
"""

import csv
import io
import json
import sqlite3
from pathlib import Path

import plotly.graph_objects as go
from flask import (Flask, Response, g, jsonify, redirect, render_template,
                   request, url_for)

from archetypes import classify, draft_score, _CLASS_BONUS, _CONF_MULTIPLIER, _POS_VALUE, _s, _height_inches

# ─── App Setup ────────────────────────────────────────────────────────────────

app = Flask(__name__)
BASE_DIR = Path(__file__).parent
DB_PATH = BASE_DIR / "scouting.db"

# ─── Data Loading (once at startup) ──────────────────────────────────────────

def _load_players():
    path = BASE_DIR / "players.json"
    if not path.exists():
        return []
    raw = json.loads(path.read_text(encoding="utf-8"))
    return raw.get("players", [])

def _load_scarcity():
    path = BASE_DIR / "scarcity.json"
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))

PLAYERS = _load_players()
PLAYERS_BY_ID = {p["id"]: p for p in PLAYERS}
SCARCITY = _load_scarcity()

# Build profiles from precomputed data
def _get_profile(p):
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

PROFILES = {p["id"]: _get_profile(p) for p in PLAYERS}

# ─── Percentile computation (once at startup) ────────────────────────────────

_PCTL_STATS = ["PPG", "RPG", "APG", "SPG", "BPG", "FG%", "3P%", "FT%", "MPG"]
_PCTL_ADV = ["PER", "TS%", "eFG%", "USG%", "BPM", "Win Shares", "WS/40"]
_PCTL_KEYS = _PCTL_STATS + _PCTL_ADV

def _build_percentiles():
    """Pre-sort stat values so we can compute any player's percentile in O(log n)."""
    from bisect import bisect_left
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

def get_percentiles(player):
    """Return {stat_key: percentile_int} for a player."""
    from bisect import bisect_left
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

TIER_LABELS = {1: "Tier 1 — Lottery", 2: "Tier 2 — Late 1st", 3: "Tier 3 — 2nd Round"}

ARCHETYPE_DESCRIPTIONS = {
    "Elite Floor General": "A top-tier point guard who controls tempo, creates for others at elite rates, and limits turnovers. Think Chris Paul — high AST%, low TOV%, efficient scoring.",
    "Floor General": "A strong facilitator who runs the offense and gets teammates involved. Solid assist numbers and court vision, but may lack the elite efficiency or turnover discipline of the top tier.",
    "Scoring Guard": "A high-usage backcourt scorer who can create his own shot consistently. Lives above 18 PPG with heavy usage — the go-to option in half-court sets.",
    "3-and-D Guard": "A two-way guard who spaces the floor with reliable three-point shooting and disrupts passing lanes on defense. Low usage, high impact.",
    "Combo Guard": "A versatile backcourt player who can score and distribute. Blends scoring punch (14+ PPG) with real playmaking (4+ APG).",
    "Three-Level Scorer": "An elite offensive weapon who can score from all three levels — at the rim, from mid-range, and behind the arc. The most translatable offensive archetype.",
    "Two-Way Star": "A dominant player who impacts both ends at a high level. Elite production combined with real defensive stats and a strong BPM. Franchise-caliber prospects.",
    "Two-Way Wing": "A wing who contributes on both ends without being elite at either. Good combination of scoring and defensive activity. Versatile rotation player.",
    "Sharpshooter": "A lights-out three-point specialist who stretches defenses. Shoots 37%+ on high volume from deep. Floor spacing is an increasingly valuable skill.",
    "Point Forward": "A forward with legitimate playmaking ability. Creates for others from the high post or in transition — a mismatch weapon. Rare and highly valued.",
    "Stretch Five": "A center who can step out and shoot threes while still protecting the rim. Floor spacing from the five spot with shot-blocking upside. Extremely scarce.",
    "Modern Big": "A versatile big man who can pass, shoot, and operate in space. Can facilitate from the elbow and hit open threes. The new prototype for big men.",
    "Post Scorer": "An efficient interior scorer who dominates in the paint with touch and footwork. High FG%, gets to the line, and finishes through contact.",
    "Glass Cleaner": "A dominant rebounder who controls the glass on both ends. Elite rebounding with strong offensive rebounding. Creates extra possessions.",
    "Old School Big": "A traditional center who operates exclusively in the paint. High FG% but no three-point range. Limited in modern spread offenses.",
    "Small Ball Five": "An undersized big who plays bigger than his height. Can shoot, pass, and switch on defense — the positionless basketball prototype.",
    "Volume Scorer": "A high-usage scorer who puts up big numbers through volume. 18+ PPG with heavy usage — can be a go-to option if efficiency develops.",
    "Secondary Scorer": "A capable scorer who thrives as a second or third option. Solid production without needing the ball constantly. Fits next to a primary creator.",
    "Playmaker": "A pass-first player who creates for teammates as his primary skill. Strong assist numbers — may not score much, but makes the offense run.",
    "Rebounder": "A player whose primary contribution is controlling the glass. Elite rebounding but limited offensive creation. Effective in the right system.",
    "Rim Protector": "A shot-blocking specialist who deters attacks at the rim. 1.5+ BPG — his defensive presence is his calling card.",
    "Role Player": "A player without a standout skill that defines his game. Solid but unspectacular. Can contribute in a specific role but likely needs development.",
    "Defensive Anchor": "An elite rim protector who anchors the entire defense. 2+ BPG with strong defensive win shares and BPM. Franchise-level defensive impact.",
    "Point of Attack Defender": "A guard who can lock up the opposing team's best ball handler. Active hands, positive defensive BPM, and quickness to stay in front.",
    "Perimeter Pest": "An aggressive perimeter defender who disrupts the offense with constant ball pressure. Gets steals and deflections but may gamble too much.",
    "Wing Stopper": "A versatile wing defender who can guard 2-4 positions. Combines steals, blocks, and positive defensive metrics — the modern switch-everything defender.",
    "Versatile Defender": "A defender who can guard multiple positions and contribute stocks across the board. Active in passing lanes and at the rim.",
    "Paint Presence": "A big man who deters shots at the rim with size and timing. 1.5+ BPG — changes the math on drives and interior passes.",
    "Weak Side Shot Blocker": "A rim protector who gets blocks primarily as a help defender. 2+ BPG but low steal numbers.",
    "Help Defender": "A positional defender who cleans up on the weak side. Good rebounding and some shot-blocking, but not an on-ball stopper.",
    "Defensive Liability": "A player with significant defensive limitations. Negative DBPM, low stocks — gets targeted by opposing offenses.",
    "No Defense": "A player who provides minimal defensive contribution. Low stocks and negative or flat defensive metrics. Must be hidden defensively.",
    "Average Defender": "A player whose defense is neither a strength nor a weakness. Does enough to stay on the floor. Neutral defensive impact.",
}

# ─── Database ─────────────────────────────────────────────────────────────────

def get_db():
    if "db" not in g:
        g.db = sqlite3.connect(str(DB_PATH))
        g.db.row_factory = sqlite3.Row
    return g.db

@app.teardown_appcontext
def close_db(exc):
    db = g.pop("db", None)
    if db:
        db.close()

def init_db():
    db = sqlite3.connect(str(DB_PATH))
    db.executescript("""
        CREATE TABLE IF NOT EXISTS notes (
            player_id INTEGER PRIMARY KEY,
            content TEXT DEFAULT '',
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS watchlist (
            player_id INTEGER PRIMARY KEY,
            added_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS boards (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS board_order (
            board_id INTEGER NOT NULL,
            player_id INTEGER NOT NULL,
            position INTEGER NOT NULL,
            PRIMARY KEY (board_id, player_id),
            FOREIGN KEY (board_id) REFERENCES boards(id) ON DELETE CASCADE
        );
    """)
    # Migrate: if old board_order has no board_id column, recreate
    cur = db.execute("PRAGMA table_info(board_order)")
    cols = [r[1] for r in cur.fetchall()]
    if "board_id" not in cols:
        db.executescript("""
            DROP TABLE IF EXISTS board_order;
            CREATE TABLE board_order (
                board_id INTEGER NOT NULL,
                player_id INTEGER NOT NULL,
                position INTEGER NOT NULL,
                PRIMARY KEY (board_id, player_id),
                FOREIGN KEY (board_id) REFERENCES boards(id) ON DELETE CASCADE
            );
        """)
    db.close()

init_db()

# ─── Helpers ──────────────────────────────────────────────────────────────────

_RADAR_COLORS = [
    ("#f59e0b", "rgba(245,158,11,0.12)"),
    ("#3b82f6", "rgba(59,130,246,0.12)"),
    ("#10b981", "rgba(16,185,129,0.12)"),
    ("#ef4444", "rgba(239,68,68,0.12)"),
    ("#8b5cf6", "rgba(139,92,246,0.12)"),
    ("#ec4899", "rgba(236,72,153,0.12)"),
]

def make_radar_json(*players):
    if not players:
        return "{}"
    cats = list(players[0]["skills"].keys())
    cats_c = cats + [cats[0]]
    fig = go.Figure()
    for i, p in enumerate(players):
        vals = list(p["skills"].values()) + [list(p["skills"].values())[0]]
        lc, fc = _RADAR_COLORS[i % len(_RADAR_COLORS)]
        fig.add_trace(go.Scatterpolar(
            r=vals, theta=cats_c, fill="toself", name=p["name"],
            line_color=lc, fillcolor=fc,
        ))
    fig.update_layout(
        polar=dict(
            radialaxis=dict(visible=True, range=[0, 100], showticklabels=False,
                            gridcolor="rgba(128,128,128,0.2)"),
            angularaxis=dict(gridcolor="rgba(128,128,128,0.2)"),
            bgcolor="rgba(0,0,0,0)",
        ),
        paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
        margin=dict(l=40, r=40, t=40, b=40),
        legend=dict(orientation="h", yanchor="bottom", y=-0.15, xanchor="center", x=0.5),
        height=360,
    )
    return fig.to_json()

def fmt_stat(val, label):
    if val is None:
        return "—"
    if label == "3P%" and val == 0.0:
        return "N/A"
    if "%" in label:
        return f"{val:.1f}%"
    if label == "GS":
        return str(int(val))
    return f"{val:.1f}"

def get_watchlist_ids():
    db = get_db()
    rows = db.execute("SELECT player_id FROM watchlist").fetchall()
    return {r["player_id"] for r in rows}

def get_notes_map():
    db = get_db()
    rows = db.execute("SELECT player_id, content FROM notes").fetchall()
    return {r["player_id"]: r["content"] for r in rows}

def get_board_order(board_id=None):
    db = get_db()
    if board_id is None:
        return {}
    rows = db.execute("SELECT player_id, position FROM board_order WHERE board_id=?", (board_id,)).fetchall()
    return {r["player_id"]: r["position"] for r in rows}

def get_all_boards():
    db = get_db()
    rows = db.execute("SELECT id, name, created_at FROM boards ORDER BY created_at").fetchall()
    return [dict(r) for r in rows]

# ─── Routes ───────────────────────────────────────────────────────────────────

@app.route("/")
def index():
    return redirect(url_for("scouting"))

@app.route("/scouting")
def scouting():
    pid = request.args.get("player_id", type=int)
    if pid and pid in PLAYERS_BY_ID:
        player = PLAYERS_BY_ID[pid]
    else:
        player = PLAYERS[0] if PLAYERS else None

    if not player:
        return "No player data loaded.", 500

    profile = PROFILES.get(player["id"], {})
    wl_ids = get_watchlist_ids()
    notes = get_notes_map()
    percentiles = get_percentiles(player)

    # Compare player (optional)
    cmp_id = request.args.get("compare", type=int)
    cmp_player = PLAYERS_BY_ID.get(cmp_id) if cmp_id else None
    cmp_profile = PROFILES.get(cmp_id, {}) if cmp_player else None
    cmp_percentiles = get_percentiles(cmp_player) if cmp_player else None

    if cmp_player:
        radar_json = make_radar_json(player, cmp_player)
    else:
        radar_json = make_radar_json(player)

    # Player search list (top 200 for dropdown)
    search_players = sorted(PLAYERS, key=lambda p: p["rank"])[:200]

    return render_template("scouting.html",
        player=player, profile=profile, radar_json=radar_json,
        in_watchlist=player["id"] in wl_ids,
        note=notes.get(player["id"], ""),
        search_players=search_players,
        all_players=PLAYERS,
        fmt_stat=fmt_stat,
        tier_labels=TIER_LABELS,
        arch_desc=ARCHETYPE_DESCRIPTIONS,
        percentiles=percentiles,
        cmp_player=cmp_player, cmp_profile=cmp_profile,
        cmp_percentiles=cmp_percentiles,
    )

@app.route("/compare")
def compare():
    ids = request.args.get("ids", "")
    selected = []
    if ids:
        for sid in ids.split(","):
            try:
                pid = int(sid.strip())
                if pid in PLAYERS_BY_ID:
                    selected.append(PLAYERS_BY_ID[pid])
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
            if key in p["stats"]:
                v = p["stats"].get(key)
            else:
                v = p["advanced"].get(key)
            vals.append(v)
            row["cells"].append(fmt_stat(v, key))
        # Find best
        numeric = [(i, v) for i, v in enumerate(vals) if v is not None and v != 0]
        best_idx = None
        if numeric:
            if key in _lower_better:
                best_idx = min(numeric, key=lambda x: x[1])[0]
            else:
                best_idx = max(numeric, key=lambda x: x[1])[0]
        row["best_idx"] = best_idx
        comp_rows.append(row)

    search_players = sorted(PLAYERS, key=lambda p: p["rank"])[:200]

    return render_template("compare.html",
        selected=selected, radar_json=radar_json,
        comp_rows=comp_rows, search_players=search_players,
        profiles=PROFILES, fmt_stat=fmt_stat,
    )

@app.route("/bigboard")
def bigboard():
    top200 = sorted(PLAYERS, key=lambda p: p["rank"])[:200]
    wl_ids = get_watchlist_ids()
    boards = get_all_boards()

    # Which board are we viewing? None = master (formula ranking)
    board_id = request.args.get("board_id", type=int)
    current_board = None
    is_master = board_id is None

    if board_id is not None:
        # Verify board exists
        db = get_db()
        row = db.execute("SELECT id, name FROM boards WHERE id=?", (board_id,)).fetchone()
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
    # else: already sorted by rank (formula order)

    for i, p in enumerate(top200):
        p["_display_pos"] = i + 1

    return render_template("bigboard.html",
        players=top200, wl_ids=wl_ids,
        tier_labels=TIER_LABELS, profiles=PROFILES,
        fmt_stat=fmt_stat,
        boards=boards, current_board=current_board,
        is_master=is_master, board_id=board_id,
    )

@app.route("/watchlist")
def watchlist():
    wl_ids = get_watchlist_ids()
    notes = get_notes_map()
    watched = [PLAYERS_BY_ID[pid] for pid in wl_ids if pid in PLAYERS_BY_ID]
    watched.sort(key=lambda p: p["rank"])

    return render_template("watchlist.html",
        players=watched, notes=notes, profiles=PROFILES,
        tier_labels=TIER_LABELS, fmt_stat=fmt_stat,
    )

@app.route("/scarcity")
def scarcity():
    return render_template("scarcity.html",
        scarcity=SCARCITY, arch_desc=ARCHETYPE_DESCRIPTIONS,
        tier_labels=TIER_LABELS,
    )

@app.route("/needs")
def needs():
    # Build list of all archetypes that exist in the top 200
    top200 = sorted(PLAYERS, key=lambda p: p["rank"])[:200]
    off_archetypes = sorted(set(
        a for p in top200 for a in PROFILES.get(p["id"], {}).get("all_offensive", []) if a
    ))
    def_archetypes = sorted(set(
        a for p in top200 for a in PROFILES.get(p["id"], {}).get("all_defensive", []) if a
    ))

    # Get selected needs from query params
    sel_off = request.args.getlist("off")
    sel_def = request.args.getlist("def")

    results = []
    if sel_off or sel_def:
        for p in top200:
            prof = PROFILES.get(p["id"], {})
            p_off = set(prof.get("all_offensive", []))
            p_def = set(prof.get("all_defensive", []))

            # Count how many needs this player fills
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

        # Sort by fit percentage desc, then draft score desc
        results.sort(key=lambda r: (-r["total_matches"], -r["player"].get("draft_score", 0)))

    return render_template("needs.html",
        off_archetypes=off_archetypes, def_archetypes=def_archetypes,
        sel_off=sel_off, sel_def=sel_def,
        results=results, profiles=PROFILES,
        tier_labels=TIER_LABELS, fmt_stat=fmt_stat,
        arch_desc=ARCHETYPE_DESCRIPTIONS,
    )

@app.route("/ranking")
def ranking():
    # Build score breakdowns for the top 10 players as live examples
    examples = []
    top10 = sorted(PLAYERS, key=lambda p: p["rank"])[:10]
    for p in top10:
        s = p.get("stats", {})
        a = p.get("advanced", {})
        pos = p.get("pos", "")
        is_g = pos == "G"
        is_c = pos == "C"

        ppg = _s(s, "PPG"); rpg = _s(s, "RPG"); apg = _s(s, "APG")
        spg = _s(s, "SPG"); bpg = _s(s, "BPG")

        if is_g:
            ppg_cap, rpg_cap, apg_cap = 23.0, 6.0, 8.0
        elif is_c:
            ppg_cap, rpg_cap, apg_cap = 19.0, 12.0, 4.0
        else:
            ppg_cap, rpg_cap, apg_cap = 23.0, 9.0, 5.0

        prod = (min(ppg/ppg_cap, 1.0)*50 + min(rpg/rpg_cap, 1.0)*15 +
                min(apg/apg_cap, 1.0)*25 + min(spg/2.5, 1.0)*10 + min(bpg/2.5, 1.0)*10)

        per = _s(a, "PER"); ts = _s(a, "TS%"); efg = _s(a, "eFG%")
        bpm = _s(a, "BPM"); fg_pct = _s(s, "FG%"); tp_pct = _s(s, "3P%")
        tpa = _s(s, "3PA"); usg = _s(a, "USG%")
        eff = 0
        if per > 0: eff += min(per/30.0, 1.0)*28
        if ts > 0: eff += min((ts-40)/25.0, 1.0)*8
        if bpm != 0 or _s(a, "Win Shares") > 0: eff += min((bpm+5)/15.0, 1.0)*8
        if efg > 0: eff += min((efg-35)/25.0, 1.0)*12
        if fg_pct > 0: eff += min((fg_pct-35)/25.0, 1.0)*6
        if tp_pct > 0 and tpa > 1:
            tp_weight = 6 if is_c else 22
            eff += min((tp_pct-25)/15.0, 1.0)*tp_weight
        if usg > 24 and ts > 56: eff += min((usg-24)/10.0, 1.0)*20

        ws = _s(a, "Win Shares"); ws40 = _s(a, "WS/40")
        impact = 0
        if ws > 0: impact += min(ws/7.0, 1.0)*60
        if ws40 > 0: impact += min(ws40/0.25, 1.0)*40

        dbpm = _s(a, "DBPM"); dws = _s(a, "DWS")
        two_way = 0
        if dbpm != 0: two_way += min((dbpm+3)/8.0, 1.0)*40
        if dws > 0: two_way += min(dws/3.0, 1.0)*30
        two_way += min((spg+bpg)/3.5, 1.0)*30

        raw = prod*0.38 + eff*0.25 + impact*0.15 + two_way*0.10

        year = p.get("year", "Unknown")
        conf = p.get("conference", "")
        age_mult = _CLASS_BONUS.get(year, 0.97)
        conf_mult = _CONF_MULTIPLIER.get(conf, 0.93)

        examples.append({
            "id": p["id"], "rank": p["rank"], "name": p["name"],
            "pos": pos, "school": p["school"], "year": year, "conf": conf,
            "prod": prod, "eff": eff, "impact": impact, "two_way": two_way,
            "raw": raw, "age_mult": age_mult, "conf_mult": conf_mult,
            "final": p.get("draft_score", 0),
        })

    class_bonuses = sorted(_CLASS_BONUS.items(),
                           key=lambda x: x[1], reverse=True)
    conf_multipliers = sorted(_CONF_MULTIPLIER.items(),
                              key=lambda x: x[1], reverse=True)
    pos_values = sorted(_POS_VALUE.items(),
                        key=lambda x: x[1], reverse=True)

    return render_template("ranking.html",
        examples=examples,
        class_bonuses=class_bonuses,
        conf_multipliers=conf_multipliers,
        pos_values=pos_values,
    )

# ─── API Endpoints ────────────────────────────────────────────────────────────

@app.route("/api/players")
def api_players():
    q = request.args.get("q", "").lower().strip()
    results = []
    for p in PLAYERS:
        if q and q not in p["name"].lower() and q not in p.get("school", "").lower() and q not in p.get("conference", "").lower():
            continue
        results.append({
            "id": p["id"], "name": p["name"], "rank": p["rank"],
            "pos": p["pos"], "school": p["school"],
            "conference": p.get("conference", ""),
        })
        if len(results) >= 50:
            break
    return jsonify(results)

@app.route("/api/notes/<int:pid>", methods=["GET", "PUT"])
def api_notes(pid):
    db = get_db()
    if request.method == "PUT":
        data = request.get_json()
        content = data.get("content", "")
        db.execute(
            "INSERT INTO notes (player_id, content) VALUES (?, ?) "
            "ON CONFLICT(player_id) DO UPDATE SET content=?, updated_at=CURRENT_TIMESTAMP",
            (pid, content, content),
        )
        db.commit()
        return jsonify({"ok": True})
    row = db.execute("SELECT content FROM notes WHERE player_id=?", (pid,)).fetchone()
    return jsonify({"content": row["content"] if row else ""})

@app.route("/api/watchlist/<int:pid>", methods=["POST", "DELETE"])
def api_watchlist(pid):
    db = get_db()
    if request.method == "POST":
        db.execute("INSERT OR IGNORE INTO watchlist (player_id) VALUES (?)", (pid,))
        db.commit()
        return jsonify({"ok": True, "action": "added"})
    db.execute("DELETE FROM watchlist WHERE player_id=?", (pid,))
    db.commit()
    return jsonify({"ok": True, "action": "removed"})

@app.route("/api/boards", methods=["POST"])
def api_board_create():
    data = request.get_json()
    name = data.get("name", "").strip()
    if not name:
        return jsonify({"ok": False, "error": "Name required"}), 400
    db = get_db()
    cur = db.execute("INSERT INTO boards (name) VALUES (?)", (name,))
    db.commit()
    return jsonify({"ok": True, "id": cur.lastrowid, "name": name})

@app.route("/api/boards/<int:bid>", methods=["PUT", "DELETE"])
def api_board_update(bid):
    db = get_db()
    if request.method == "DELETE":
        db.execute("DELETE FROM board_order WHERE board_id=?", (bid,))
        db.execute("DELETE FROM boards WHERE id=?", (bid,))
        db.commit()
        return jsonify({"ok": True})
    data = request.get_json()
    name = data.get("name", "").strip()
    if not name:
        return jsonify({"ok": False, "error": "Name required"}), 400
    db.execute("UPDATE boards SET name=? WHERE id=?", (name, bid))
    db.commit()
    return jsonify({"ok": True})

@app.route("/api/board/<int:bid>/reorder", methods=["POST"])
def api_board_reorder(bid):
    data = request.get_json()
    order = data.get("order", [])
    db = get_db()
    db.execute("DELETE FROM board_order WHERE board_id=?", (bid,))
    for i, pid in enumerate(order):
        db.execute("INSERT INTO board_order (board_id, player_id, position) VALUES (?, ?, ?)",
                   (bid, pid, i + 1))
    db.commit()
    return jsonify({"ok": True})

@app.route("/api/export/bigboard.csv")
def export_bigboard():
    top200 = sorted(PLAYERS, key=lambda p: p["rank"])[:200]
    board_id = request.args.get("board_id", type=int)
    board_order = get_board_order(board_id)
    for p in top200:
        p["_board_pos"] = board_order.get(p["id"], p["rank"])
    top200.sort(key=lambda p: p["_board_pos"])

    out = io.StringIO()
    w = csv.writer(out)
    w.writerow(["Board Rank", "Name", "Pos", "School", "Conference", "Year",
                "Height", "Draft Score", "Tier", "Archetype", "PPG", "RPG", "APG"])
    for i, p in enumerate(top200):
        pos = i + 1
        tier = 1 if pos <= 15 else (2 if pos <= 45 else 3)
        prof = PROFILES.get(p["id"], {})
        w.writerow([pos, p["name"], p["pos"], p["school"], p.get("conference", ""),
                     p["year"], p["height"], round(p.get("draft_score", 0), 1),
                     TIER_LABELS.get(tier, ""), prof.get("primary", ""),
                     p["stats"].get("PPG"), p["stats"].get("RPG"), p["stats"].get("APG")])

    return Response(out.getvalue(), mimetype="text/csv",
                    headers={"Content-Disposition": "attachment; filename=big_board.csv"})

@app.route("/api/export/watchlist.csv")
def export_watchlist():
    wl_ids = get_watchlist_ids()
    notes = get_notes_map()
    watched = [PLAYERS_BY_ID[pid] for pid in wl_ids if pid in PLAYERS_BY_ID]
    watched.sort(key=lambda p: p["rank"])

    out = io.StringIO()
    w = csv.writer(out)
    w.writerow(["Rank", "Name", "Pos", "School", "Conference", "Year",
                "Draft Score", "Archetype", "PPG", "RPG", "APG", "Notes"])
    for p in watched:
        prof = PROFILES.get(p["id"], {})
        w.writerow([p["rank"], p["name"], p["pos"], p["school"],
                     p.get("conference", ""), p["year"],
                     round(p.get("draft_score", 0), 1), prof.get("primary", ""),
                     p["stats"].get("PPG"), p["stats"].get("RPG"),
                     p["stats"].get("APG"), notes.get(p["id"], "")])

    return Response(out.getvalue(), mimetype="text/csv",
                    headers={"Content-Disposition": "attachment; filename=watchlist.csv"})

# ─── Run ──────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    app.run(debug=True, port=5001)
