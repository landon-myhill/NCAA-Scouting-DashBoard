"""
core.names — canonical player-name normalization, matching, and stable IDs.

The ONE definition of name handling. Previously `_norm`/`_norm_name` existed in
6 files (analyze_history, backtest_lib, rerank, merge_*, scrape_*) in slightly
different forms — a drift hazard for the whole matching pipeline.
"""

import hashlib
import re
import unicodedata

_SUFFIX_RE = re.compile(r"\s+(jr|sr|ii|iii|iv|v)\.?$")
_PUNCT_RE = re.compile(r"[^\w\s]")
_SPACE_RE = re.compile(r"\s+")


def normalize_name(name: str) -> str:
    """Lowercase, strip accents/punctuation/suffixes, collapse whitespace.

    'Kasparas Jakučionis Jr.' -> 'kasparas jakucionis'
    """
    name = unicodedata.normalize("NFKD", name or "")
    name = "".join(c for c in name if not unicodedata.combining(c))
    name = name.lower().strip()
    name = _SUFFIX_RE.sub("", name)
    name = _PUNCT_RE.sub("", name)
    name = _SPACE_RE.sub(" ", name)
    return name.strip()


def name_keys(name: str) -> tuple[str, str]:
    """Return (full_norm, 'first_initial last') — the second is a nickname-
    tolerant fallback matching both 'Lou Hutchinson' and 'Louis Hutchinson'."""
    full = normalize_name(name)
    parts = full.split()
    if len(parts) >= 2:
        return full, f"{parts[0][0]} {parts[-1]}"
    return full, full


def stable_id(name: str, school: str) -> int:
    """Deterministic positive 31-bit id derived from a player's identity.

    Unlike a sort-position id, this is stable across re-scrapes, so SQLite
    notes / watchlist / board rows keep pointing at the same human season over
    season. Collisions across ~4k players are astronomically unlikely; callers
    that build an id->player map should still guard against the rare clash.
    """
    key = f"{normalize_name(name)}|{normalize_name(school)}".encode("utf-8")
    digest = hashlib.sha1(key).hexdigest()
    return int(digest[:8], 16) & 0x7FFFFFFF


def match_player(pick: dict, by_norm: dict, by_school: dict):
    """Match a draft pick (dict with 'player' and optional 'college') to an NCAA
    player record. Returns the record or None. Strategy: exact normalized name,
    then school-scoped last-name match, then first-initial+last-name fallback.
    """
    n = normalize_name(pick.get("player", ""))
    if n in by_norm:
        return by_norm[n]

    school = (pick.get("college") or "").strip()
    if school and n:
        for p in by_school.get(school, []):
            if normalize_name(p.get("name", "")).endswith(n.split()[-1]):
                return p

    parts = n.split()
    if len(parts) >= 2:
        key = f"{parts[0][0]} {parts[-1]}"
        for full, p in by_norm.items():
            fp = full.split()
            if len(fp) >= 2 and f"{fp[0][0]} {fp[-1]}" == key:
                return p
    return None
