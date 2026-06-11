"""
model.strengths — measured strengths + archetype FIT scores.

Design (user-specified):
  1. Every player gets ~10 STRENGTH percentiles (0-100), each computed
     relative to his position group among draft-relevant players. These are
     measurements, not opinions — and they replace nothing in the draft
     score: fits NEVER touch the ranking.
  2. Every archetype is a RECIPE: positive weights over strengths. No recipe
     ever penalizes an extra skill — a slasher with a jumper simply also
     posts a big Three-Level fit (versatility = multiple high fits).
  3. Fit scores are re-percentiled within each archetype's eligible
     population -> "effectiveness percentile": how elite at that role.
  4. A player's profile is his TOP fits; his badge is his best fit. Everyone
     is a role player somewhere — the percentile says how good a one.

Physical tools enter where basketball says they should (size/length in the
defensive and finishing recipes). Age/combine-athleticism extensions are
planned next, per the project owner.
"""

from bisect import bisect_left
from functools import lru_cache

from core.numeric import height_inches, safe_stat as _s

REFERENCE_N = 300          # draft-relevant population per season file

# Physical measurables are graded against ALL classes pooled, not the class:
# a 7'0 wingspan means the same thing in 2020 and 2026, class pools are small
# (~60-100), and class composition (a guard-heavy year) shouldn't move a
# center's size percentile. Production strengths stay class-relative —
# dominance is always vs your actual competition.
PHYSICAL_KEYS = ("size",)
SECONDARY_BADGE_PCT = 75   # second offensive badge only if genuinely elite

STRENGTH_KEYS = [
    "scoring", "shooting", "playmaking", "finishing", "rim_pressure",
    "rebounding", "rim_protection", "perimeter_defense", "ball_security",
    "size",
]


def _per36(v, mpg):
    return v * 36.0 / max(mpg, 15.0) if mpg > 0 else v


def _raw_strengths(p: dict) -> dict:
    """Raw (un-percentiled) strength metrics for one player. None = unknown."""
    s, a = p.get("stats", {}), p.get("advanced", {})
    mpg = _s(s, "MPG")
    ppg36 = _per36(_s(s, "PPG"), mpg)
    rpg36 = _per36(_s(s, "RPG"), mpg)
    apg36 = _per36(_s(s, "APG"), mpg)
    spg36 = _per36(_s(s, "SPG"), mpg)
    bpg36 = _per36(_s(s, "BPG"), mpg)
    oreb36 = _per36(_s(s, "OREB"), mpg)
    fta36 = _per36(_s(s, "FTA"), mpg)
    tpa, fga = _s(s, "3PA"), _s(s, "FGA")
    tp, fg, ft = _s(s, "3P%"), _s(s, "FG%"), _s(s, "FT%")
    dbpm, ast_pct, tov_pct = _s(a, "DBPM"), _s(a, "AST%"), _s(a, "TOV%")

    # Interior finishing: 2P% recovered from makes (FG% blends in threes)
    fin = None
    if fga > 0 and fg > 0:
        fgm = fg / 100.0 * fga
        tpm = (tp / 100.0) * tpa if tpa > 0 else 0.0
        two_att = fga - tpa
        if two_att > 1.5:
            fin = (fgm - tpm) / two_att * 100.0

    # Shooting: made threes x accuracy above replacement, plus FT touch
    shoot = None
    if tpa >= 0.5 and tp > 0:
        tpm36 = _per36(tp / 100.0 * tpa, mpg)
        shoot = tpm36 * max(tp - 25.0, 0.0) + 0.15 * max(ft - 60.0, 0.0)
    elif fga > 2:
        shoot = 0.0  # real sample, doesn't shoot threes

    ftr = (fta36 / _per36(fga, mpg)) if fga > 1 else None

    combine = p.get("combine") or {}
    ht = combine.get("height_w_shoes_in") or height_inches(p.get("height", ""))
    wing = combine.get("wingspan_in")
    size = None
    if ht:
        size = ht + (0.5 * (wing - ht * 1.04) if wing else 0.0)  # length credit vs typical +4% wingspan

    return {
        "scoring": ppg36 if mpg > 0 else None,
        "shooting": shoot,
        "playmaking": (ast_pct + apg36 * 2) if (ast_pct > 0 or apg36 > 0) else None,
        "finishing": (fin + 12 * ftr) if (fin is not None and ftr is not None) else fin,
        "rim_pressure": (fta36 + (20 * ftr if ftr else 0)) if fta36 > 0 else None,
        "rebounding": rpg36 + 0.5 * oreb36 if mpg > 0 else None,
        "rim_protection": (bpg36 * 3 + max(dbpm, 0)) if mpg > 0 else None,
        "perimeter_defense": (spg36 * 3 + 0.6 * max(dbpm, 0)) if mpg > 0 else None,
        "ball_security": -tov_pct if tov_pct > 0 else None,
        "size": size,
    }


def _pos_group(p: dict) -> str:
    return p.get("pos") if p.get("pos") in ("G", "F", "C") else "F"


@lru_cache(maxsize=1)
def _pooled_physical_ref() -> dict:
    """Sorted raw values for PHYSICAL_KEYS over every curated class pool
    (board members across all season files + the current season). Falls back
    to {} (class reference) if the files aren't available."""
    try:
        from core.config import HISTORY_DIR, PLAYERS_FILE
        from core.jsonio import load_json
        pool = []
        for f in sorted(HISTORY_DIR.glob("players_*.json")):
            pool += [p for p in load_json(f).get("players", [])
                     if p.get("_mock_rank")]
        cur = load_json(PLAYERS_FILE)
        cur = cur["players"] if isinstance(cur, dict) else cur
        pool += [p for p in cur if p.get("_mock_rank")]
    except Exception:
        return {}
    out = {}
    for pos in ("G", "F", "C", "all"):
        grp = pool if pos == "all" else [p for p in pool if _pos_group(p) == pos]
        raws = [_raw_strengths(p) for p in grp]
        for k in PHYSICAL_KEYS:
            out[(pos, k)] = sorted(r[k] for r in raws if r[k] is not None)
    return out


def compute_strengths(players: list[dict], reference: list[dict] | None = None,
                      reference_n: int = REFERENCE_N) -> None:
    """Stamp p['strengths'] = {key: 0-100 percentile vs his position group}.

    `reference` is the population percentiles are measured against — pass the
    CURATED DRAFT POOL when one exists, so a 95 means "95th percentile in
    this draft class at his position". Falls back to the board top-N.
    """
    ref = reference if reference else players[:reference_n]
    sorted_ref: dict = {}
    for pos in ("G", "F", "C", "all"):
        grp = ref if pos == "all" else [p for p in ref if _pos_group(p) == pos]
        raws = [(_raw_strengths(p)) for p in grp]
        for k in STRENGTH_KEYS:
            vals = sorted(r[k] for r in raws if r[k] is not None)
            sorted_ref[(pos, k)] = vals
    for key, vals in _pooled_physical_ref().items():  # physical: all classes
        if vals:
            sorted_ref[key] = vals

    for p in players:
        raw = _raw_strengths(p)
        pos = _pos_group(p)
        out, out_abs = {}, {}
        for k in STRENGTH_KEYS:
            v = raw[k]
            for scale, dest in ((pos, out), ("all", out_abs)):
                vals = sorted_ref.get((scale, k), [])
                if v is None or not vals:
                    dest[k] = None
                else:
                    dest[k] = round(bisect_left(vals, v) / len(vals) * 100)
        p["strengths"] = out          # vs his position group ("good for a guard")
        p["strengths_abs"] = out_abs  # vs everyone ("good, period") — used by
                                      # recipes for absolute jobs like rebounding


# ── Archetype recipes: POSITIVE weights only ─────────────────────────────────
# {name: (eligible positions, {strength: weight}, gate)}. Weights sum to 1.
# A recipe describes what the role IS — never what it isn't: a slasher with a
# jumper LOSES nothing, he just also rates as a Three-Level Scorer.
#
# Two scales (the audit caught why both are needed):
#   plain key  -> position-relative percentile ("elite for a guard")
#   key@abs    -> absolute percentile vs everyone — for jobs measured in
#                 absolute terms. A guard who rebounds great FOR A GUARD is
#                 not a Glass Cleaner; a center whose steals are elite FOR A
#                 CENTER is not a Switch Defender.
#
# Gates are STYLE eligibility, not quality penalties: "Slasher" is a
# perimeter-attack role, "Connector" is by definition low-usage glue.

def _perimeter_oriented(p):  # guards always; forwards only with a real perimeter diet
    s = p.get("stats", {})
    fga, tpa = _s(s, "FGA"), _s(s, "3PA")
    return _pos_group(p) == "G" or (fga > 0 and tpa / fga >= 0.15)


def _low_usage(p):
    usg = _s(p.get("advanced", {}), "USG%")
    return 0 < usg < 22


OFFENSE_RECIPES = {
    "Floor General":      (("G",),          {"playmaking": .55, "ball_security": .30, "scoring": .15}, None),
    "Scoring Guard":      (("G",),          {"scoring": .55, "shooting": .25, "finishing": .20}, None),
    "Combo Guard":        (("G",),          {"scoring": .35, "playmaking": .35, "shooting": .15, "ball_security": .15}, None),
    "Slasher":            (("G", "F"),      {"rim_pressure": .35, "finishing": .30, "scoring": .35}, _perimeter_oriented),
    "Sharpshooter":       (("G", "F"),      {"shooting": .75, "scoring": .15, "ball_security": .10}, None),
    "Stretch Big":        (("F", "C"),      {"shooting": .60, "scoring": .20, "rebounding": .20}, None),
    "Three-Level Scorer": (("G", "F"),      {"scoring": .35, "shooting": .30, "finishing": .25, "rim_pressure": .10}, None),
    "Connector":          (("G", "F"),      {"playmaking": .30, "ball_security": .25, "perimeter_defense": .25, "shooting": .10, "finishing": .10}, _low_usage),
    "Offensive Hub":      (("F", "C"),      {"playmaking": .45, "scoring": .30, "finishing": .15, "ball_security": .10}, None),
    "Post Scorer":        (("F", "C"),      {"scoring": .35, "finishing": .35, "rim_pressure": .15, "rebounding@abs": .15}, None),
    "Play Finisher":      (("F", "C"),      {"finishing": .45, "rim_protection@abs": .20, "rebounding@abs": .20, "rim_pressure": .15}, None),
    "Glass Cleaner":      (("G", "F", "C"), {"rebounding@abs": .70, "rim_protection@abs": .15, "finishing": .15}, None),
}

DEFENSE_RECIPES = {
    "Switch Defender":          (("G", "F", "C"), {"perimeter_defense@abs": .45, "rim_protection@abs": .45, "size@abs": .10}, None),
    "Rim Protector":            (("F", "C"),      {"rim_protection@abs": .65, "size@abs": .20, "rebounding@abs": .15}, None),
    "Point-of-Attack Defender": (("G",),          {"perimeter_defense": .80, "size": .20}, None),
    "Wing Stopper":             (("F",),          {"perimeter_defense@abs": .60, "rim_protection@abs": .20, "size@abs": .20}, None),
}

ALL_RECIPES = {**OFFENSE_RECIPES, **DEFENSE_RECIPES}


def _fit_raw(p: dict, recipe: dict):
    rel = p.get("strengths") or {}
    ab = p.get("strengths_abs") or {}
    parts = []
    for k, w in recipe.items():
        if k.endswith("@abs"):
            parts.append((w, ab.get(k[:-4])))
        else:
            parts.append((w, rel.get(k)))
    have = [(w, v) for w, v in parts if v is not None]
    if sum(w for w, _ in have) < 0.6:   # too little data to claim a fit
        return None
    wsum = sum(w for w, _ in have)
    return sum(w * v for w, v in have) / wsum


def compute_fits(players: list[dict], reference: list[dict] | None = None,
                 reference_n: int = REFERENCE_N) -> None:
    """Stamp p['fits'] = {archetype: effectiveness percentile (0-100)} over
    every archetype the player's position is eligible for, percentiled
    within the eligible reference population (pass the curated draft pool).
    Also stamps badge fields: archetype / all_offensive (<=2) / defensive /
    all_defensive (<=1)."""
    ref = reference if reference else players[:reference_n]
    ref_sorted: dict = {}
    for name, (poss, recipe, gate) in ALL_RECIPES.items():
        vals = sorted(v for p in ref
                      if _pos_group(p) in poss and (gate is None or gate(p))
                      for v in [_fit_raw(p, recipe)] if v is not None)
        ref_sorted[name] = vals

    for p in players:
        pos = _pos_group(p)
        fits = {}
        for name, (poss, recipe, gate) in ALL_RECIPES.items():
            if pos not in poss or (gate is not None and not gate(p)):
                continue
            v = _fit_raw(p, recipe)
            vals = ref_sorted[name]
            if v is None or not vals:
                continue
            fits[name] = round(bisect_left(vals, v) / len(vals) * 100)
        p["fits"] = fits

        off = sorted(((n, v) for n, v in fits.items() if n in OFFENSE_RECIPES),
                     key=lambda x: -x[1])
        dfn = sorted(((n, v) for n, v in fits.items() if n in DEFENSE_RECIPES),
                     key=lambda x: -x[1])
        p["archetype"] = off[0][0] if off else ""
        p["all_offensive"] = [n for n, v in off[:2]
                              if v >= SECONDARY_BADGE_PCT or (off and n == off[0][0])]
        if dfn and dfn[0][1] >= 60:
            p["defensive_archetype"] = dfn[0][0]
        elif dfn and dfn[0][1] <= 20:
            p["defensive_archetype"] = "Defensive Liability"
        else:
            p["defensive_archetype"] = "Average Defender"
        p["all_defensive"] = [p["defensive_archetype"]]
