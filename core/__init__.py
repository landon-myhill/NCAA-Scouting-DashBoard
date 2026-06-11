"""
core — shared foundation for the NCAA Scouting Dashboard.

Everything that used to be copy-pasted across the 16 root scripts lives here
once: name normalization/matching, numeric parsing, JSON I/O, config, and
data validation. Import from here instead of re-defining helpers.
"""

from core.config import (
    SEASON_YEAR, SEASON_LABEL, BASE_DIR, PLAYERS_FILE, SCARCITY_FILE,
    HISTORY_DIR, DB_PATH, POWER_CONFERENCES, season_label_for,
)
from core.numeric import flt, pct, height_inches, safe_stat
from core.names import normalize_name, name_keys, match_player, stable_id
from core.jsonio import load_json, save_json, load_players

__all__ = [
    "SEASON_YEAR", "SEASON_LABEL", "BASE_DIR", "PLAYERS_FILE", "SCARCITY_FILE",
    "HISTORY_DIR", "DB_PATH", "POWER_CONFERENCES", "season_label_for",
    "flt", "pct", "height_inches", "safe_stat",
    "normalize_name", "name_keys", "match_player", "stable_id",
    "load_json", "save_json", "load_players",
]
