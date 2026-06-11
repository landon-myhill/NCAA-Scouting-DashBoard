"""JSON + CSV API routes."""

import csv
import io

from flask import Blueprint, Response, jsonify, request

from web import store
from web.content import TIER_LABELS
from web.db import (get_board_order, get_db, get_notes_map, get_watchlist_ids)

api_bp = Blueprint("api", __name__, url_prefix="/api")


@api_bp.route("/players")
def players_search():
    q = request.args.get("q", "").lower().strip()
    results = []
    for p in store.PLAYERS:
        if (q and q not in p["name"].lower()
                and q not in p.get("school", "").lower()
                and q not in p.get("conference", "").lower()):
            continue
        results.append({
            "id": p["id"], "name": p["name"], "rank": p["rank"],
            "pos": p["pos"], "school": p["school"],
            "conference": p.get("conference", ""),
        })
        if len(results) >= 50:
            break
    return jsonify(results)


@api_bp.route("/notes/<int:pid>", methods=["GET", "PUT"])
def notes(pid):
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


@api_bp.route("/watchlist/<int:pid>", methods=["POST", "DELETE"])
def watchlist(pid):
    db = get_db()
    if request.method == "POST":
        db.execute("INSERT OR IGNORE INTO watchlist (player_id) VALUES (?)", (pid,))
        db.commit()
        return jsonify({"ok": True, "action": "added"})
    db.execute("DELETE FROM watchlist WHERE player_id=?", (pid,))
    db.commit()
    return jsonify({"ok": True, "action": "removed"})


@api_bp.route("/boards", methods=["POST"])
def board_create():
    data = request.get_json()
    name = data.get("name", "").strip()
    if not name:
        return jsonify({"ok": False, "error": "Name required"}), 400
    db = get_db()
    cur = db.execute("INSERT INTO boards (name) VALUES (?)", (name,))
    db.commit()
    return jsonify({"ok": True, "id": cur.lastrowid, "name": name})


@api_bp.route("/boards/<int:bid>", methods=["PUT", "DELETE"])
def board_update(bid):
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


@api_bp.route("/board/<int:bid>/reorder", methods=["POST"])
def board_reorder(bid):
    data = request.get_json()
    order = data.get("order", [])
    db = get_db()
    db.execute("DELETE FROM board_order WHERE board_id=?", (bid,))
    for i, pid in enumerate(order):
        db.execute("INSERT INTO board_order (board_id, player_id, position) VALUES (?, ?, ?)",
                   (bid, pid, i + 1))
    db.commit()
    return jsonify({"ok": True})


@api_bp.route("/export/bigboard.csv")
def export_bigboard():
    # View copies — never mutate the shared global player objects (see views.bigboard).
    pool, _, _ = store.board_filter(store.PLAYERS, store.CURRENT_SEASON_YEAR)
    top200 = [dict(p) for p in sorted(pool, key=lambda p: p["rank"])[:200]]
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
        prof = store.PROFILES.get(p["id"], {})
        w.writerow([pos, p["name"], p["pos"], p["school"], p.get("conference", ""),
                    p["year"], p["height"], round(p.get("draft_score", 0), 1),
                    TIER_LABELS.get(tier, ""), prof.get("primary", ""),
                    p["stats"].get("PPG"), p["stats"].get("RPG"), p["stats"].get("APG")])

    return Response(out.getvalue(), mimetype="text/csv",
                    headers={"Content-Disposition": "attachment; filename=big_board.csv"})


@api_bp.route("/export/watchlist.csv")
def export_watchlist():
    wl_ids = get_watchlist_ids()
    notes_map = get_notes_map()
    watched = [store.PLAYERS_BY_ID[pid] for pid in wl_ids if pid in store.PLAYERS_BY_ID]
    watched.sort(key=lambda p: p["rank"])

    out = io.StringIO()
    w = csv.writer(out)
    w.writerow(["Rank", "Name", "Pos", "School", "Conference", "Year",
                "Draft Score", "Archetype", "PPG", "RPG", "APG", "Notes"])
    for p in watched:
        prof = store.PROFILES.get(p["id"], {})
        w.writerow([p["rank"], p["name"], p["pos"], p["school"],
                    p.get("conference", ""), p["year"],
                    round(p.get("draft_score", 0), 1), prof.get("primary", ""),
                    p["stats"].get("PPG"), p["stats"].get("RPG"),
                    p["stats"].get("APG"), notes_map.get(p["id"], "")])

    return Response(out.getvalue(), mimetype="text/csv",
                    headers={"Content-Disposition": "attachment; filename=watchlist.csv"})
