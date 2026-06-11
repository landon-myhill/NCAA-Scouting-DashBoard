"""
core.validation — sanity checks on scraped player data.

sports-reference.com changes its HTML periodically. When it does, the scraper
silently emits rows full of None instead of crashing, and a bad board ships.
These checks turn that silent failure into a loud one.
"""


class DataValidationError(Exception):
    pass


REQUIRED_TOP_KEYS = {"name", "pos", "school", "conference", "year", "stats", "advanced"}
# Core stats that should be present for the large majority of players. If the
# null-rate for one of these blows past the threshold, the scrape is suspect.
KEY_STATS = ["PPG", "RPG", "APG", "MPG", "FG%"]
KEY_ADVANCED = ["PER", "TS%", "BPM", "Win Shares"]


def validate_players(players: list[dict], *, min_count: int = 2000,
                     max_null_rate: float = 0.40, strict: bool = True) -> list[str]:
    """Return a list of warning strings; raise DataValidationError in strict
    mode if any hard check fails.

    Hard checks: minimum row count, required keys present, stat null-rate.
    Defaults are tuned for a full D1 season (~4000 players).
    """
    problems: list[str] = []

    if len(players) < min_count:
        problems.append(
            f"Only {len(players)} players (expected >= {min_count}); scrape likely incomplete."
        )

    missing_keys = set()
    for p in players[:50]:
        missing_keys |= REQUIRED_TOP_KEYS - set(p.keys())
    if missing_keys:
        problems.append(f"Players missing required keys: {sorted(missing_keys)}")

    n = max(len(players), 1)
    for key, src in [(k, "stats") for k in KEY_STATS] + [(k, "advanced") for k in KEY_ADVANCED]:
        nulls = sum(1 for p in players if (p.get(src) or {}).get(key) is None)
        rate = nulls / n
        if rate > max_null_rate:
            problems.append(
                f"{src}.{key} is null for {rate:.0%} of players (>{max_null_rate:.0%}); "
                f"sports-reference layout may have changed."
            )

    # Duplicate-id check (stable ids should be unique per scrape).
    ids = [p.get("id") for p in players if p.get("id") is not None]
    if ids and len(set(ids)) != len(ids):
        problems.append(f"Duplicate player ids: {len(ids) - len(set(ids))} collisions.")

    if strict and problems:
        raise DataValidationError("\n".join(" - " + p for p in problems))
    return problems
