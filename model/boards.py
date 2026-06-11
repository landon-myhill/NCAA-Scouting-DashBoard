"""
model.boards — curated class-pool matching, shared by the pipeline and the
web app. A board list (datasets/board_lists/board_<year>.txt) defines a
draft class's ELIGIBLE population; this module matches its names to player
records. Line order is the consensus mock rank (stamped as _mock_rank).
"""

from core.config import BOARD_LISTS_DIR
from core.names import name_keys, normalize_name


def load_board(year, players):
    """Return (ids_set, unmatched) for a season's curated list, or (None, [])
    when no list file exists. unmatched = [(name, school, mock_rank), ...].
    Stamps _mock_rank on matched player dicts."""
    path = BOARD_LISTS_DIR / f"board_{year}.txt"
    if not path.exists():
        return None, []
    by_norm: dict = {}
    by_initial: dict = {}
    for p in players:
        full, initial = name_keys(p["name"])
        by_norm.setdefault(full, []).append(p)
        by_initial.setdefault(initial, []).append(p)

    def _school_scope(cands, school):
        sc = normalize_name(school)
        scoped = [p for p in cands
                  if sc in normalize_name(p.get("school", ""))
                  or normalize_name(p.get("school", "")) in sc]
        return scoped or cands

    ids, unmatched = set(), []
    mock_rank = 0  # the list's line order IS the consensus mock ranking
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.split("#")[0].strip()
        if not line:
            continue
        mock_rank += 1
        name, _, school = (s.strip() for s in line.partition("|"))
        cands = by_norm.get(normalize_name(name), [])
        if not cands:  # nickname-tolerant fallback: first initial + last name
            _, initial = name_keys(name)
            cands = by_initial.get(initial, [])
            # A fallback hit is a weaker claim — when the list names a school,
            # demand agreement, or "Malique Lewis (NBL)" grabs Mikey Lewis
            # (Saint Mary's) and a stranger ends up on the board.
            if cands and school:
                sc = normalize_name(school)
                cands = [p for p in cands
                         if sc in normalize_name(p.get("school", ""))
                         or normalize_name(p.get("school", "")) in sc]
        if len(cands) > 1 and school:
            cands = _school_scope(cands, school)
        if cands:
            # if still ambiguous, take the most prominent (best-ranked) match
            best = min(cands, key=lambda p: p["rank"])
            best["_mock_rank"] = mock_rank
            ids.add(best["id"])
        else:
            unmatched.append((name, school, mock_rank))
    return ids, unmatched
