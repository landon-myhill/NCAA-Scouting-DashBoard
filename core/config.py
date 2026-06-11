"""
core.config — single source of truth for season, paths, and shared constants.

Previously the active season was hard-coded in BOTH scrape.py (YEAR=2026) and
app.py (CURRENT_SEASON_YEAR=2026) and kept in sync by hand. Now it lives here.
Override at runtime with the SCOUT_SEASON_YEAR environment variable.
"""

import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent

# Active draft cycle. 2026 == the 2025-26 NCAA season.
SEASON_YEAR = int(os.environ.get("SCOUT_SEASON_YEAR", "2026"))


def season_label_for(year: int) -> str:
    """2026 -> '2025-26'."""
    return f"{year - 1}-{str(year)[2:]}"


SEASON_LABEL = season_label_for(SEASON_YEAR)

# ── Paths (all anchored to the repo root, so scripts work from any subpackage) ──
# Every scraped/generated data file lives under datasets/ — the root stays code-only.
DATASETS_DIR = BASE_DIR / "datasets"
PLAYERS_FILE = DATASETS_DIR / "players.json"
SCARCITY_FILE = DATASETS_DIR / "scarcity.json"
DRAFT_ELIGIBLE_FILE = DATASETS_DIR / "draft_eligible.json"
DRAFT_OVERRIDES_FILE = DATASETS_DIR / "draft_overrides.json"
REPORTS_FILE = DATASETS_DIR / "reports.json"
STARS_FILE = DATASETS_DIR / "stars_list.json"
# Optional curated big-board filters, one file per season:
#   datasets/board_lists/board_<year>.txt  ("Name | School" per line, # comments)
# When a season's file exists, its big board shows ONLY those players.
BOARD_LISTS_DIR = DATASETS_DIR / "board_lists"
# Scraped international/G-League pre-draft stats: datasets/intl/intl_<year>.json
INTL_DIR = DATASETS_DIR / "intl"
HISTORY_DIR = DATASETS_DIR / "history"
COMBINE_DIR = DATASETS_DIR / "combine"
COMBINE_RAW_DIR = COMBINE_DIR / "raw"
RECRUITS_DIR = DATASETS_DIR / "recruits"
RECRUITS_RAW_DIR = RECRUITS_DIR / "raw"
DB_PATH = DATASETS_DIR / "scouting.db"

# ── Domain constants ─────────────────────────────────────────────────────────
# Power-six conferences. Used in board face-validity checks and elsewhere; was
# previously redefined in archetypes.py, analyze_history.py, and ad-hoc scripts.
POWER_CONFERENCES = frozenset({
    "ACC", "SEC", "Big Ten", "Big 12", "Big East", "Pac-12",
})

# Draft classes whose NBA careers are mature enough to use as ground truth.
MATURE_DRAFT_YEARS = (2020, 2021, 2022, 2023)
