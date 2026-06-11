#!/usr/bin/env python3
"""
migrate_ids.py — one-shot migration from positional player ids to STABLE ids.

Why: player ids used to be the sort position (id == rank). Re-scraping a new
season reassigned every id, so SQLite notes / watchlist / board rows silently
re-pointed at different humans. Stable ids (hash of name+school) fix that going
forward — this script migrates EXISTING data so nothing is orphaned:

  1. Builds old_positional_id -> new_stable_id from the current players.json
  2. Rewrites players.json with stable ids (rank/tier unchanged)
  3. Remaps notes, watchlist, draft_entrants, board_order in scouting.db

Idempotent: if players.json already uses stable ids, it does nothing.

    python -m scripts.migrate_ids
"""

import sqlite3
import sys

from core import DB_PATH, PLAYERS_FILE, load_json, save_json
from data.scrape import assign_ids_ranks

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

_DB_TABLES = ["notes", "watchlist", "draft_entrants", "board_order"]


def _looks_positional(players) -> bool:
    """True if ids are still 1..N in order (the old positional scheme)."""
    return all(p.get("id") == i + 1 for i, p in enumerate(players))


def migrate() -> None:
    raw = load_json(PLAYERS_FILE)
    if not raw or "players" not in raw:
        print("No players.json to migrate.")
        return
    players = raw["players"]

    if not _looks_positional(players):
        print("players.json already uses stable ids — nothing to migrate.")
        return

    old_ids = [p.get("id") for p in players]
    assign_ids_ranks(players)  # assigns stable ids (+ rank/tier) in place
    mapping = {old: p["id"] for old, p in zip(old_ids, players)}
    print(f"Built id map for {len(mapping)} players (positional -> stable).")

    save_json(PLAYERS_FILE, raw)
    print(f"Rewrote {PLAYERS_FILE.name} with stable ids.")

    if not DB_PATH.exists():
        print("No scouting.db yet — DB migration skipped.")
        return

    db = sqlite3.connect(str(DB_PATH))
    try:
        existing = {r[0] for r in db.execute(
            "SELECT name FROM sqlite_master WHERE type='table'")}
        total = 0
        for table in _DB_TABLES:
            if table not in existing:
                continue
            rows = db.execute(f"SELECT rowid, player_id FROM {table}").fetchall()
            moved, dropped = 0, 0
            for rowid, pid in rows:
                new = mapping.get(pid)
                if new is None:
                    db.execute(f"DELETE FROM {table} WHERE rowid=?", (rowid,))
                    dropped += 1
                elif new != pid:
                    db.execute(f"UPDATE {table} SET player_id=? WHERE rowid=?", (new, rowid))
                    moved += 1
            if rows:
                print(f"  {table}: {moved} remapped, {dropped} dropped (no longer present)")
                total += moved
        db.commit()
        print(f"DB migration complete ({total} rows remapped).")
    finally:
        db.close()


if __name__ == "__main__":
    migrate()
