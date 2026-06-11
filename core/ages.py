"""
core.ages — true draft-day age lookup (scraped by data.scrape_ages).

age_for(name, year, school) returns the Tankathon draft-day age in years
(e.g. 19.4) or None. Matching mirrors model.boards: exact normalized name
first, then first-initial + surname — but the fallback only fires when the
school agrees (the Boopie/Kevin Miller lesson: name fuzz without school
agreement creates false positives).

class_age_fallback(class_year) is the honest imputation for players the
scrape doesn't cover (undrafted training rows, deep stubs): the mean scraped
age of that class year, computed from the data itself.
"""

from functools import lru_cache

from core.config import DATASETS_DIR
from core.jsonio import load_json
from core.names import normalize_name

_PATH = DATASETS_DIR / "ages.json"

# Known name variants: our normalized name -> Tankathon's normalized key.
_ALIASES = {
    "kj martin": "kenyon martin",
    "cam thomas": "cameron thomas",
    "brandon boston": "bj boston",
    "oliviermaxence prosper": "oliviermaxen prosper",
    "bub carrington": "carlton carrington",
    "yanic konan niederhauser": "ya konan niederhauser",
}


@lru_cache(maxsize=1)
def _data() -> dict:
    if not _PATH.exists():
        return {}
    return load_json(_PATH).get("by_year", {})


@lru_cache(maxsize=1)
def _fallbacks() -> dict:
    """Mean scraped age per class-year string, e.g. {'Freshman': 19.3, ...}."""
    sums: dict[str, list] = {}
    for rows in _data().values():
        for r in rows.values():
            cls = (r.get("class") or "").strip()
            if cls and r.get("age"):
                sums.setdefault(cls, []).append(r["age"])
    return {cls: round(sum(v) / len(v), 2) for cls, v in sums.items() if v}


def _norm_school(s: str) -> str:
    return normalize_name(s or "").replace("state", "st")


def age_for(name: str, year: int | str, school: str = "") -> float | None:
    table = _data().get(str(year))
    if not table:
        return None
    key = normalize_name(name)
    hit = table.get(key) or table.get(_ALIASES.get(key, ""))
    if hit:
        return hit["age"]
    # first-initial + surname, school must agree
    parts = key.split()
    if len(parts) < 2 or not school:
        return None
    want = (parts[0][0], parts[-1], _norm_school(school))
    for k, r in table.items():
        kp = k.split()
        if len(kp) >= 2 and (kp[0][:1], kp[-1]) == want[:2] \
                and _norm_school(r.get("school", "")) == want[2]:
            return r["age"]
    return None


def class_age_fallback(class_year: str) -> float | None:
    """Imputed age for an unscraped player, from his class-year peers."""
    cls = (class_year or "").strip()
    if cls in ("Graduate", "5th Year"):  # Tankathon folds these into Senior
        v = _fallbacks().get("Senior")
        return round(v + 1.0, 2) if v else None
    return _fallbacks().get(cls)
