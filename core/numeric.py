"""
core.numeric — robust numeric parsing for scraped stat cells.

Replaces the copies of flt()/pct()/_height_inches()/_s() that were scattered
across scrape.py, parse_combine.py, archetypes.py, analyze_traits.py, etc.
"""

_EMPTY = {"", "—", "-", "–", "N/A", ".", "None"}


def flt(val, default=None):
    """Parse a scraped value to float, tolerating empty/placeholder cells."""
    if val is None:
        return default
    if isinstance(val, (int, float)):
        return float(val)
    s = str(val).strip()
    if s in _EMPTY:
        return default
    try:
        return float(s)
    except (ValueError, TypeError):
        return default


def pct(val):
    """Normalize a percentage to display scale: 0.452 -> 45.2, 45.2 -> 45.2."""
    v = flt(val)
    if v is None:
        return None
    return round(v * 100, 1) if 0 < v <= 1.0 else round(v, 1)


def safe_stat(stats: dict, key: str, default=0) -> float:
    """Get stats[key], substituting `default` for missing/None values."""
    if not stats:
        return default
    v = stats.get(key)
    return v if v is not None else default


def height_inches(height: str) -> int:
    """Convert a height string like 6'9\" or 6-9 to total inches. 0 if unparseable."""
    if not height:
        return 0
    try:
        h = str(height)
        if "'" in h:
            ft, inch = h.replace('"', "").split("'")
            return int(ft) * 12 + int(inch or 0)
        if "-" in h:
            ft, inch = h.split("-", 1)
            return int(ft) * 12 + int(inch or 0)
    except (ValueError, IndexError):
        pass
    return 0
