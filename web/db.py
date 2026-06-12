"""SQLite persistence: scout notes, watchlist, draft toggles, custom boards."""

import sqlite3

from flask import g

from core import DB_PATH


def get_db() -> sqlite3.Connection:
    if "db" not in g:
        g.db = sqlite3.connect(str(DB_PATH))
        g.db.row_factory = sqlite3.Row
    return g.db


def close_db(exc=None):
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
        CREATE TABLE IF NOT EXISTS draft_entrants (
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
        CREATE TABLE IF NOT EXISTS mocks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            picks TEXT NOT NULL DEFAULT '[]',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
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


# ── Read helpers used by routes ───────────────────────────────────────────────

def get_watchlist_ids() -> set:
    rows = get_db().execute("SELECT player_id FROM watchlist").fetchall()
    return {r["player_id"] for r in rows}


def get_notes_map() -> dict:
    rows = get_db().execute("SELECT player_id, content FROM notes").fetchall()
    return {r["player_id"]: r["content"] for r in rows}


def get_board_order(board_id=None) -> dict:
    if board_id is None:
        return {}
    rows = get_db().execute(
        "SELECT player_id, position FROM board_order WHERE board_id=?", (board_id,)
    ).fetchall()
    return {r["player_id"]: r["position"] for r in rows}


def get_all_boards() -> list[dict]:
    rows = get_db().execute(
        "SELECT id, name, created_at FROM boards ORDER BY created_at"
    ).fetchall()
    return [dict(r) for r in rows]
