"""
NCAA Draft Scout — Player Archetype Classification & Draft Scoring
-------------------------------------------------------------------
Classifies players into archetypes and tags based on their stats.
Provides composite draft scoring for realistic draft board ranking.
"""


from core.numeric import safe_stat as _s, height_inches as _height_inches


# ── Position height thresholds (inches) ──────────────────────────────────────

_UNDERSIZED = {"G": 73, "F": 77, "C": 81}
_PLUS_SIZE  = {"G": 76, "F": 80, "C": 84}
_POWER_CONFS = {"ACC", "SEC", "Big Ten", "Big 12", "Big East", "Pac-12"}


# ── Age/class year draft value multiplier ────────────────────────────────────
_CLASS_BONUS = {
    "Freshman": 1.05,
    "Sophomore": 1.02,
    "Junior": 1.00,
    "Senior": 0.97,
    "Graduate": 0.94,
    "5th Year": 0.92,
    "Unknown": 0.98,
}

# ── Conference strength multiplier ───────────────────────────────────────────
_CONF_MULTIPLIER = {
    "Big Ten": 1.08, "SEC": 1.08, "Big 12": 1.07, "ACC": 1.06,
    "Big East": 1.04, "Pac-12": 1.04, "WCC": 1.0, "Mountain West": 0.98,
    "AAC": 0.97, "A-10": 0.96, "MVC": 0.95,
}

# ── Position value (modern NBA values wings/guards slightly more) ────────────
_POS_VALUE = {
    "G": 1.03, "F": 1.02, "C": 0.98,
}


def draft_score(player: dict, weights: dict | None = None, return_parts: bool = False):
    """
    Compute a composite draft score for ranking players.

    weights:      override the DEFAULT_WEIGHTS blend (used by the tuner).
    return_parts: return the raw component dict instead of the final score
                  (lets the tuner score every player once, then re-blend cheaply).

    Weights:
      - Production (PPG, RPG, APG, SPG, BPG)    ~30%
      - Efficiency (PER, TS%, BPM, eFG%)         ~30%
      - Impact (Win Shares, WS/40)               ~15%
      - Two-way value (DBPM, DWS, SPG+BPG)      ~10%
      - Multipliers (age, conference, position)   ~15%

    Higher score = higher draft pick.
    """
    s = player.get("stats", {})
    a = player.get("advanced", {})

    ppg = _s(s, "PPG")
    rpg = _s(s, "RPG")
    apg = _s(s, "APG")
    spg = _s(s, "SPG")
    bpg = _s(s, "BPG")
    tov = _s(s, "TOV")
    fta = _s(s, "FTA")

    per = _s(a, "PER")
    ts  = _s(a, "TS%")
    efg = _s(a, "eFG%")
    bpm = _s(a, "BPM")
    dbpm = _s(a, "DBPM")
    ws  = _s(a, "Win Shares")
    ws40 = _s(a, "WS/40")
    dws = _s(a, "DWS")
    tov_pct = _s(a, "TOV%")

    # ── Production score (0-100 scale, position-specific caps) ──────────────
    # Per-36 normalization: NBA scouts evaluate per-minute production, not raw
    # per-game volume. A freshman big on a deep team (Cenac, Quaintance) gets
    # buried by per-game stats but shines per-36. Floor MPG at 15 so garbage-
    # time bursts don't get extrapolated wildly.
    pos = player.get("pos", "")
    is_g = pos == "G"
    is_c = pos == "C"
    # Position-specific caps AND weights. The old formula used the same 50/15/25/10/10
    # weights for every position, which over-rewarded a center for passing he's not
    # asked to do. Centers now get more credit for rebounds and blocks, less for assists.
    if is_g:
        ppg_cap, rpg_cap, apg_cap = 23.0, 6.0, 8.0
        w_ppg, w_rpg, w_apg, w_spg, w_bpg = 50, 10, 25, 10, 5
    elif is_c:
        ppg_cap, rpg_cap, apg_cap = 19.0, 12.0, 4.0
        w_ppg, w_rpg, w_apg, w_spg, w_bpg = 40, 30, 10, 5, 15
    else:  # SF, PF, F
        ppg_cap, rpg_cap, apg_cap = 23.0, 9.0, 5.0
        w_ppg, w_rpg, w_apg, w_spg, w_bpg = 45, 20, 15, 10, 10

    mpg = _s(s, "MPG")
    scale = 36.0 / max(mpg, 15.0) if mpg > 0 else 1.0
    ppg36 = ppg * scale
    rpg36 = rpg * scale
    apg36 = apg * scale
    spg36 = spg * scale
    bpg36 = bpg * scale

    prod = (
        min(ppg36 / ppg_cap, 1.0) * w_ppg +
        min(rpg36 / rpg_cap, 1.0) * w_rpg +
        min(apg36 / apg_cap, 1.0) * w_apg +
        min(spg36 / 2.5, 1.0) * w_spg +
        min(bpg36 / 2.5, 1.0) * w_bpg
    )

    # ── Efficiency score (0-100 scale) ───────────────────────────────────────
    usg = _s(a, "USG%")
    fg_pct = _s(s, "FG%")
    tp_pct = _s(s, "3P%")
    tpa = _s(s, "3PA")

    eff = 0
    if per > 0:
        eff += min(per / 30.0, 1.0) * 28       # PER (raised)
    if ts > 0:
        eff += min((ts - 40) / 25.0, 1.0) * 8   # TS% (lowered)
    if bpm != 0 or ws > 0:
        eff += min((bpm + 5) / 15.0, 1.0) * 8   # BPM (lowered)
    # eFG% is missing for many players in the dataset; fall back to a
    # computed approximation from FG%/3P data so we don't penalize them.
    efg_use = efg
    if efg_use <= 0:
        fg_p = _s(s, "FG%")
        tp_p = _s(s, "3P%")
        tp_att = _s(s, "3PA")
        fg_att = _s(s, "FGA")
        if fg_p > 0 and fg_att > 0:
            efg_use = fg_p + 50.0 * (tp_p / 100.0) * (tp_att / fg_att)
    if efg_use > 0:
        eff += min((efg_use - 35) / 25.0, 1.0) * 12  # eFG% (raised)
    # Shooting: FG% and 3P%
    if fg_pct > 0:
        eff += min((fg_pct - 35) / 25.0, 1.0) * 6    # FG% (lowered)
    # 3P% — guards/wings weighted heavy, centers low (not expected to shoot)
    if tp_pct > 0 and tpa > 1:
        tp_weight = 6 if is_c else 22
        eff += min((tp_pct - 25) / 15.0, 1.0) * tp_weight
    # Usage-efficiency bonus: high usage + high TS% = shot creator.
    # Reduced from +20 to +8 max: USG% alone has a negative trait signal
    # (-0.21) — high-USG college players don't reliably become NBA stars
    # (often "best on a bad team" types). We keep a small bonus for the
    # specific combo of high USG with elite efficiency.
    if usg > 24 and ts > 56:
        eff += min((usg - 24) / 10.0, 1.0) * 8

    # Elite shooter bonus (Bane archetype: senior knockdown shooter).
    # Softened: star-list analysis showed star wings averaged only 35% from
    # 3 in college. Pure college shooting is overrated as a star predictor.
    # Reduced bonus from +10 max to +5 max — still rewards genuine snipers
    # but doesn't elevate pure-shooter specialists too aggressively.
    if tpa > 5 and tp_pct > 38:
        eff += 3 + min((tp_pct - 38) * 0.25, 2)

    # ── Impact score (0-100 scale) ───────────────────────────────────────────
    # WS is the strongest individual signal among advanced volume metrics in
    # our trait analysis (signal +0.32), so we lean into it slightly more.
    impact = 0
    if ws > 0:
        impact += min(ws / 7.0, 1.0) * 70       # Win Shares (was 60)
    if ws40 > 0:
        impact += min(ws40 / 0.25, 1.0) * 30    # WS/40 (was 40)

    # ── Two-way score (0-100 scale) ──────────────────────────────────────────
    # Stocks are scaled per position (a guard can't block shots from the
    # perimeter): denominators sit near each position's ~90th percentile so
    # the stocks term pays G/F/C at comparable rates instead of handing
    # bigs a structural +5-9 points.
    _STOCKS_CAP = {"G": 2.5, "F": 3.0, "C": 3.0}
    two_way = 0
    if dbpm != 0:
        two_way += min((dbpm + 3) / 8.0, 1.0) * 40   # DBPM
    if dws > 0:
        two_way += min(dws / 3.0, 1.0) * 30           # DWS
    two_way += min((spg + bpg) / _STOCKS_CAP.get(pos, 3.0), 1.0) * 30  # stocks

    # NOTE: the two-way score is now PURELY stat-based (DBPM/DWS/stocks). It used
    # to be blended 60/40 with the hand-rolled `skills.Defense` heuristic from
    # derive_skills() — but that heuristic was never validated against NBA
    # outcomes, and letting an unvalidated grade feed the scored formula is
    # circular. The scout grade still drives archetype LABELS in classify(),
    # just not the ranking. The two_way weight was re-fit after this change.

    # ── Playmaking bonus (the strongest star-vs-starter differentiator) ────
    # Trait analysis of confirmed NBA stars (Mobley, Haliburton, Bane, Edwards,
    # Barnes, Maxey) showed APG is the LARGEST positive gap between stars and
    # starters in college (+1.51 APG on average). Bigs/wings with playmaking
    # are especially predictive (Mobley, Cade Cunningham, Scottie Barnes).
    ast_pct = _s(a, "AST%")
    play_bonus = 0
    if apg > 3.5:
        play_bonus += min((apg - 3.5), 3.5) * 1.5      # up to +5 for high APG
    if apg > 6:
        play_bonus += 3                                 # elite distributor
    # Big/wing playmaking — Mobley, Cade, Barnes, future Banchero types
    if pos in ("F", "C") and apg > 3:
        play_bonus += 3
        if apg > 4:
            play_bonus += 2  # truly rare bigman creation

    # ── Minutes floor ────────────────────────────────────────────────────────
    # With per-36 production above, MPG no longer biases the rate stats.
    # We only penalize *truly* limited roles (<15 MPG) where the sample is
    # too small to trust regardless of normalization. No more starter bonus
    # — per-36 already captures per-minute impact.
    min_bonus = 0
    if mpg > 0 and mpg < 15:
        min_bonus = -4

    # ── Turnover penalty (TOV% is our strongest single predictor) ────────────
    # Trait analysis: TOV% signal is -0.50, by far the largest of any stat.
    # Median TOV% across drafted players is ~14%. We scale from there.
    tov_pen = 0
    if tov_pct > 0:
        tov_pen = max(0, (tov_pct - 14) * 1.2)
    if tov > 3.5:
        tov_pen += (tov - 3.5) * 1.0

    # ── Free throw signal (continuous, signal +0.33) ─────────────────────────
    # FT% is a meaningful skill predictor — touch + composure transfer to the
    # NBA. Replace the binary FT bonus with a continuous bonus/penalty
    # centered on 75% (decent college FT%), only counted if they actually
    # got to the line enough to be informative.
    ft_pct = _s(s, "FT%")
    ft_bonus = 0
    if fta > 2 and ft_pct > 0:
        if ft_pct > 75:
            ft_bonus = min(6.0, (ft_pct - 75) * 0.4)
        else:
            ft_bonus = max(-6.0, (ft_pct - 75) * 0.5)

    # ── Weighted composite ───────────────────────────────────────────────────
    # Star-list analysis (n=42 NBA stars) revealed: bigs become stars with
    # modest PPG (~10) but ELITE advanced metrics (BPM 8.3, PER 25.2, WS/40
    # 0.20). Across positions, advanced metrics discriminated stars from
    # busts better than volume. Production weight down, impact weight up.
    #
    # NOTE: the actual blend now happens in combine_parts() using WEIGHTS, so
    # the formula is data-tunable against real NBA outcomes (see backtest_lib).
    # This block just hands the raw building blocks off.

    # ── Multipliers ──────────────────────────────────────────────────────────
    year = player.get("year", "Unknown")
    conf = player.get("conference", "")

    age_mult = _CLASS_BONUS.get(year, 0.95)
    conf_mult = _CONF_MULTIPLIER.get(conf, 0.93)
    pos_mult = _POS_VALUE.get(pos, 1.0)

    # ── Size bonus (reduced — only for 6'10"+) ──────────────────────────────
    # ── Height bonus/penalty (position-relative, per inch from average) ─────
    # Average heights: PG=75(6'3"), SG=77(6'5"), SF=79(6'7"), PF=81(6'9"), C=83(6'11")
    # Prefer combine-measured with-shoes height (the standard the position
    # averages were calibrated against); fall back to college-listed height.
    _POS_AVG_HT = {"G": 75, "F": 80, "C": 83}
    combine = player.get("combine") or {}
    ht_combine = combine.get("height_w_shoes_in")
    ht = ht_combine if ht_combine else _height_inches(player.get("height", ""))
    avg_ht = _POS_AVG_HT.get(pos, 79)
    size_bonus = 0
    if ht > 0:
        diff = ht - avg_ht  # positive = taller than avg for position
        if diff >= 3:
            size_bonus = 4.0
        elif diff >= 2:
            size_bonus = 2.5
        elif diff >= 1:
            size_bonus = 1.0
        elif diff <= -3:
            size_bonus = -4.0
        elif diff <= -2:
            size_bonus = -2.5
        elif diff <= -1:
            size_bonus = -1.0

    # Hand-crafted "prospect bonuses" (freshman size premium, young creator
    # allowance, defensive prospect bonus, power-conference freshman ceiling)
    # were removed. They retro-fit known stars into the formula instead of
    # letting college stats + combine measurements speak for themselves.
    # Youth is still rewarded via the age multiplier below; size is rewarded
    # via the position-relative size_bonus and combine anthro_bonus.
    prospect_size = 0
    prospect_bonus = 0

    # ── Elite advanced metrics (true star signal) ──────────────────────────
    # POSITION-FAIR thresholds: the partial tier sits at each position's
    # ~75th percentile (top-300 board) and the full tier at its ~90th, so the
    # same share of guards, forwards, and centers can clear each bar. The old
    # bars let forwards qualify at 3-5x the guard rate (F bar below their
    # p75, G bar above their p90), which structurally buried guards on the
    # board — avg elite contribution was F 20.8 vs G 7.6.
    _ELITE_BARS = {
        #        BPM hi/lo   PER hi/lo   WS40 hi/lo
        "G": (10.5, 8.0, 24.5, 22.0, 0.21, 0.19),
        "F": (11.5, 10.0, 28.0, 25.5, 0.24, 0.21),
        "C": (9.0, 8.0, 26.0, 24.5, 0.23, 0.21),
    }
    b_hi, b_lo, p_hi, p_lo, w_hi, w_lo = _ELITE_BARS.get(pos, _ELITE_BARS["F"])
    elite_metrics = 0
    if bpm > b_hi:    elite_metrics += 5
    elif bpm > b_lo:  elite_metrics += 3
    if per > p_hi:    elite_metrics += 3
    elif per > p_lo:  elite_metrics += 1.5
    if ws40 > w_hi:   elite_metrics += 3
    elif ws40 > w_lo: elite_metrics += 1.5

    # ── HS recruit-rank bonus ───────────────────────────────────────────────
    # The single biggest gap in pure-stats prediction: scouts had YEARS of
    # pre-college data on Edwards (#5 ESPN recruit), Maxey (#11), Barnes
    # (#4 recruit class 2020) that the college box score couldn't see.
    # Top-24 McDonald's All-American players become NBA contributors at a
    # dramatically higher rate than unranked recruits. This bonus encodes
    # the pre-college consensus that no other input captures.
    recruit_bonus = 0
    rr = player.get("recruit_rank")
    if rr is not None:
        if rr <= 3:    recruit_bonus = 14   # generational tier
        elif rr <= 8:  recruit_bonus = 10   # top recruit
        elif rr <= 15: recruit_bonus = 7    # high-major lock
        elif rr <= 24: recruit_bonus = 4    # McDonald's-tier

    # ── Combine anthro bonus ────────────────────────────────────────────────
    # Trait analysis of drafted players (n=79) showed real signal:
    #   wingspan signal = +0.35,  hand_length signal = +0.41
    # Athletic-test results (vertical, sprint, agility) had near-zero signal
    # so they are deliberately excluded — workout warriors don't translate.
    # Plus-length (wingspan - height) was a wash; raw wingspan is what matters.
    anthro_bonus = 0
    wingspan = combine.get("wingspan_in")
    hand_length = combine.get("hand_length_in")
    if wingspan:
        if wingspan >= 86:    anthro_bonus += 4    # 7'2"+, elite length
        elif wingspan >= 84:  anthro_bonus += 2.5  # 7'0"+
        elif wingspan >= 82:  anthro_bonus += 1    # 6'10"+
    if hand_length:
        if hand_length >= 9.5:   anthro_bonus += 2
        elif hand_length >= 9.0: anthro_bonus += 1

    parts = {
        # 0-100 component scores (blended pre-multiplier)
        "prod": prod, "eff": eff, "impact": impact, "two_way": two_way,
        # additive bonuses/penalties applied pre-multiplier
        "play": play_bonus, "ft": ft_bonus, "min": min_bonus, "tov": tov_pen,
        # multipliers on the pre-multiplier subtotal
        "age_mult": age_mult, "conf_mult": conf_mult, "pos_mult": pos_mult,
        # additive bonuses applied post-multiplier
        "size": size_bonus + prospect_size + prospect_bonus,
        "anthro": anthro_bonus, "elite": elite_metrics, "recruit": recruit_bonus,
    }
    if return_parts:
        return parts
    return round(combine_parts(parts, weights), 2)


# ── Tunable blend ────────────────────────────────────────────────────────────
# These weights are DATA-FIT, not hand-tuned. They come from a ridge regression
# of the score components against BLENDED NBA VALUE (career WS + VORP + tier
# percentile) on the 2020-2023 draft classes, validated with leave-one-year-out
# cross-validation. See tune.py / backtest_lib.py to reproduce.
#
#   held-out Spearman vs NBA value:  old hand-tuned +0.339  ->  this +0.358
#
# What the fit learned (signed = sign of correlation with NBA success):
#   size/elite/recruit/two_way/impact  -> strongest predictors (up-weighted)
#   eff (efficiency)                   -> NEGATIVE: noise once others are in
#   conference & age stay MULTIPLICATIVE (the multipliers below). They look
#   like "noise" within the drafted pool only because that pool is almost all
#   power-conference & one-and-done — across the FULL board they're essential
#   to avoid over-ranking mid-major stat-compilers. (Selection bias: the
#   drafted-only eval set can't see that error.)
DEFAULT_WEIGHTS = {
    # component blend (ridge-fit; 'eff' is negative — efficiency adds noise).
    # Re-fit after severing the scout-skill blend from two_way (see above).
    "prod": 0.1582, "eff": -0.1546, "impact": 0.3004, "two_way": 0.5290,
    # bonus scalars (ridge-fit). 'min'/'tov' kept as fixed guards, not fit
    # (degenerate near-constant features whose fitted coef is unreliable).
    "play": 1.6987, "ft": 0.4959, "min": 0.8, "tov": 0.8,
    "size": 4.4048, "anthro": 2.0662, "elite": 3.0118, "recruit": 2.6739,
    # multiplier dampening: effective_mult = 1 + damp*(mult-1). 1.0 = unchanged.
    "age_damp": 1.0, "conf_damp": 1.0, "pos_damp": 1.0,
}


def combine_parts(parts: dict, weights: dict | None = None) -> float:
    """Blend the raw score parts into a final draft score using `weights`.

    Structure (validated hybrid): a linear blend of ALL additive components,
    scaled by the conference / age / position multipliers. Keeping the
    multipliers multiplicative — rather than folding them into the linear fit —
    is what preserves full-board sanity (see DEFAULT_WEIGHTS note).
    """
    w = weights or DEFAULT_WEIGHTS

    def _damp(mult, key):
        d = w.get(key, 1.0)
        return 1.0 + d * (mult - 1.0)

    raw = (
        parts["prod"] * w["prod"]
        + parts["eff"] * w["eff"]
        + parts["impact"] * w["impact"]
        + parts["two_way"] * w["two_way"]
        + parts["play"] * w["play"]
        + parts["ft"] * w["ft"]
        + parts["size"] * w["size"]
        + parts["anthro"] * w["anthro"]
        + parts["elite"] * w["elite"]
        + parts["recruit"] * w["recruit"]
        + parts["min"] * w["min"]      # 'min' part is 0 or -4 (low-minutes penalty)
        - parts["tov"] * w["tov"]      # 'tov' part is a penalty magnitude (>=0)
    )
    return raw * _damp(parts["age_mult"], "age_damp") \
              * _damp(parts["conf_mult"], "conf_damp") \
              * _damp(parts["pos_mult"], "pos_damp")


# FG% means different things for different shot diets: in the top-300 board
# sample, rim-heavy players (<10% of attempts from three) post a MEDIAN 60.2
# FG% while jumper-heavy players (>50%) post 42.5 — an 18-point gap from shot
# mix alone. So "efficient" is judged against the player's own diet, measured
# from his actual attempts (3PA/FGA), never assumed from position. Bars sit at
# roughly each diet bucket's 60th/75th percentile. (TS% already credits threes
# and FTs — it's largely diet-robust and stays absolute.)
def _diet_fg_bars(tpa: float, fga: float) -> tuple[float, float]:
    """(good, elite) FG% bars for this player's jumper share (3PA/FGA)."""
    share = (tpa / fga) if fga > 0 else 0.0
    if share < 0.10:
        return 62.0, 65.0   # rim-heavy
    if share < 0.30:
        return 53.0, 55.0   # mixed
    if share < 0.50:
        return 47.0, 49.0   # jumper-lean
    return 44.0, 46.0       # jumper-heavy


def classify(player: dict) -> dict:
    """
    Classify a player into archetypes and tags.

    Returns:
        {
            "primary": str,                  # Primary offensive archetype
            "defensive": str,                # Primary defensive archetype
            "all_offensive": list[str],      # All matching offensive archetypes
            "all_defensive": list[str],      # All matching defensive archetypes
            "tags": list[str],               # All applicable tags
            "red_flags": list[str],          # Warning tags
        }
    """
    s = player.get("stats", {})
    a = player.get("advanced", {})
    pos = player.get("pos", "?")
    year = player.get("year", "")
    height = player.get("height", "")
    rank = player.get("rank", 999)
    conf = player.get("conference", "")

    ppg = _s(s, "PPG")
    rpg = _s(s, "RPG")
    apg = _s(s, "APG")
    spg = _s(s, "SPG")
    bpg = _s(s, "BPG")
    fg = _s(s, "FG%")
    tp = _s(s, "3P%")
    ft = _s(s, "FT%")
    mpg = _s(s, "MPG")
    gs = _s(s, "GS")
    tov = _s(s, "TOV")
    fta = _s(s, "FTA")
    oreb = _s(s, "OREB")
    dreb = _s(s, "DREB")
    tpa = _s(s, "3PA")
    fga = _s(s, "FGA")
    pf = _s(s, "PF")

    per = _s(a, "PER")
    ts = _s(a, "TS%")
    efg = _s(a, "eFG%")
    usg = _s(a, "USG%")
    ast_pct = _s(a, "AST%")
    tov_pct = _s(a, "TOV%")
    bpm = _s(a, "BPM")
    obpm = _s(a, "OBPM")
    dbpm = _s(a, "DBPM")
    ows = _s(a, "OWS")
    dws = _s(a, "DWS")
    ws = _s(a, "Win Shares")
    ws40 = _s(a, "WS/40")

    ht = _height_inches(height)
    fg_good, fg_elite = _diet_fg_bars(tpa, fga)  # shot-diet-relative FG% bars
    is_guard = pos in ("G",)
    is_wing = pos in ("G", "F")
    is_big = pos in ("F", "C")
    is_young = year in ("Freshman", "Sophomore")
    is_veteran = year in ("Senior", "Graduate", "5th Year")

    primary = None
    defensive = None
    all_offensive = []
    all_defensive = []
    tags = []
    red_flags = []

    # ═══════════════════════════════════════════════════════════════════════════
    # OFFENSIVE ARCHETYPES — collect ALL that qualify, no fallbacks
    # ═══════════════════════════════════════════════════════════════════════════

    # Guards
    if is_guard and apg > 6 and ast_pct > 25 and tov_pct < 18 and ts > 55:
        all_offensive.append("Elite Floor General")
    if is_guard and apg > 6 and ast_pct > 25:
        all_offensive.append("Floor General")
    if is_guard and ppg > 18 and usg > 25:
        all_offensive.append("Scoring Guard")
    if is_guard and tp > 36 and spg > 1.2 and usg < 22:
        all_offensive.append("3-and-D Guard")
    if is_guard and ppg > 14 and apg > 4:
        all_offensive.append("Combo Guard")

    # Wings
    if is_wing:
        if ppg > 16 and fg > 44 and tp > 34 and fta > 3:
            all_offensive.append("Three-Level Scorer")
        if ppg > 16 and (spg + bpg) > 1.5 and bpm > 5:
            all_offensive.append("Two-Way Star")
        if tp > 37 and tpa > 4:
            all_offensive.append("Sharpshooter")
        if pos == "F" and apg > 3.5:
            all_offensive.append("Point Forward")

    # Two-Way Wing only if NOT already a Two-Way Star (it's strictly weaker)
    if is_wing and ppg > 12 and (spg + bpg) > 1.5 and "Two-Way Star" not in all_offensive:
        all_offensive.append("Two-Way Wing")

    # Bigs
    if is_big:
        if pos == "C" and tpa > 2 and tp > 30 and bpg > 1:
            all_offensive.append("Stretch Five")
        if pos in ("C", "F") and apg > 2 and tp > 30:
            all_offensive.append("Modern Big")
        if fg > fg_good and ppg > 14 and fta > 3:
            all_offensive.append("Post Scorer")
        if rpg > 8 and oreb > 2:
            all_offensive.append("Glass Cleaner")
        if fg > fg_good and tpa < 1 and rpg > 8:
            all_offensive.append("Old School Big")
        if pos in ("C", "F") and ht > 0 and ht < 80 and apg > 2 and tp > 30:
            all_offensive.append("Small Ball Five")

    # Suppress overlapping general archetypes:
    # - Floor General suppresses Playmaker (FG is more specific)
    # - Glass Cleaner suppresses Rebounder (GC is more specific)
    # - Scoring Guard / Three-Level Scorer suppress Volume Scorer
    # - Elite Floor General suppresses Floor General
    _off_set = set(all_offensive)
    _has_scorer = _off_set & {"Scoring Guard", "Three-Level Scorer", "Two-Way Star"}
    _has_passer = _off_set & {"Elite Floor General", "Floor General"}
    _has_boards = _off_set & {"Glass Cleaner"}
    _has_elite_fg = "Elite Floor General" in _off_set

    if _has_elite_fg:
        all_offensive = [a for a in all_offensive if a != "Floor General"]
    if not _has_scorer and ppg > 18 and usg > 25:
        all_offensive.append("Volume Scorer")
    if not _has_passer and apg > 5:
        all_offensive.append("Playmaker")
    if not _has_boards and rpg > 8:
        all_offensive.append("Rebounder")
    if bpg > 1.5 and "Stretch Five" not in _off_set:
        all_offensive.append("Rim Protector")

    # Deduplicate while preserving order
    seen_off = set()
    unique_off = []
    for a in all_offensive:
        if a not in seen_off:
            seen_off.add(a)
            unique_off.append(a)
    all_offensive = unique_off

    # Primary is the first match; empty list means no archetype
    primary = all_offensive[0] if all_offensive else None

    # ═══════════════════════════════════════════════════════════════════════════
    # DEFENSIVE ARCHETYPES — collect ALL that qualify, no fallbacks
    # ═══════════════════════════════════════════════════════════════════════════

    if bpg > 2 and dws > 1.5 and dbpm > 2:
        all_defensive.append("Defensive Anchor")
    if is_guard and spg > 1.5 and dbpm > 0:
        all_defensive.append("Point of Attack Defender")
    if spg > 1.5 and not is_big:
        all_defensive.append("Perimeter Pest")
    if is_wing and spg > 1 and bpg > 0.5 and dbpm > 0:
        all_defensive.append("Wing Stopper")
    if spg > 1 and bpg > 0.8 and dbpm > 0:
        all_defensive.append("Versatile Defender")
    if is_big and bpg > 1.5:
        all_defensive.append("Paint Presence")
    if bpg > 2 and spg < 0.5:
        all_defensive.append("Weak Side Shot Blocker")
    if dreb > 5 and bpg > 1 and spg < 0.8:
        all_defensive.append("Help Defender")
    if dbpm < -2 and spg < 0.8 and bpg < 0.5:
        all_defensive.append("Defensive Liability")

    # Suppress overlaps:
    # - Defensive Anchor suppresses Paint Presence and Weak Side Shot Blocker
    # - Defensive Liability is exclusive (can't also be No Defense)
    _def_set = set(all_defensive)
    if "Defensive Anchor" in _def_set:
        all_defensive = [a for a in all_defensive if a not in ("Paint Presence", "Weak Side Shot Blocker")]
    if "Defensive Liability" not in _def_set and dbpm < -1 and spg < 0.8 and bpg < 0.5:
        all_defensive.append("No Defense")

    # Scout-grade defense override. The hand-scouted Defense rating is more
    # reliable than stocks (which can come from gambling) or DBPM (which rides
    # team defense). When the scout flags a weak defender, strip out the
    # positive stat-based defensive archetypes AND the "Two-Way" offensive
    # labels that imply defensive ability — otherwise we'd label the same
    # player both "Perimeter Pest" and "Below-Average Defender".
    _POSITIVE_DEF = {
        "Defensive Anchor", "Point of Attack Defender", "Perimeter Pest",
        "Wing Stopper", "Versatile Defender", "Paint Presence",
        "Weak Side Shot Blocker", "Help Defender",
    }
    skill_def = player.get("skills", {}).get("Defense")
    # Stat veto: if on-court defensive impact is clearly elite, the scout
    # grade can't override it (it's likely just an inaccurate/stale grade).
    elite_def_stats = dbpm > 2.5 and dws > 1.5
    if isinstance(skill_def, (int, float)) and not elite_def_stats:
        if skill_def < 30:
            all_defensive = [a for a in all_defensive if a not in _POSITIVE_DEF]
            all_offensive = [a for a in all_offensive if a not in ("Two-Way Star", "Two-Way Wing")]
            if "Defensive Liability" not in all_defensive and "No Defense" not in all_defensive:
                all_defensive.append("Defensive Liability")
        elif skill_def < 45:
            all_defensive = [a for a in all_defensive if a not in _POSITIVE_DEF]
            all_offensive = [a for a in all_offensive if a not in ("Two-Way Star", "Two-Way Wing")]
            if "Defensive Liability" not in all_defensive:
                all_defensive.append("Below-Average Defender")

    # Average Defender: fallback for players who don't qualify for anything else
    if not all_defensive:
        all_defensive.append("Average Defender")

    # Deduplicate
    seen_def = set()
    unique_def = []
    for a in all_defensive:
        if a not in seen_def:
            seen_def.add(a)
            unique_def.append(a)
    all_defensive = unique_def

    # Primary defensive is the first match; empty means none qualified
    defensive = all_defensive[0] if all_defensive else None

    # ═══════════════════════════════════════════════════════════════════════════
    # TAGS
    # ═══════════════════════════════════════════════════════════════════════════

    # ── Scoring Style ────────────────────────────────────────────────────────
    if ppg > 18 and usg > 25 and tp > 34:
        tags.append("Shot Creator")
    if fg > fg_elite and tpa < 2 and fta > 3:
        tags.append("Rim Finisher")
    if ppg > 16 and fg > 44 and tp > 34 and fta > 3:
        tags.append("Three-Level Scorer")
    if ppg > 18 and usg > 28:
        tags.append("Primary Option")
    if 12 <= ppg <= 18 and 20 <= usg <= 28:
        tags.append("Secondary Scorer")
    if ppg < 12 and bpm > 0:
        tags.append("Tertiary Piece")
    if usg < 20 and tp > 36 and apg < 2:
        tags.append("Spot Up Role")
    if usg < 22 and ppg > 10 and efg > 52:
        tags.append("Off-Ball Mover")
    if ppg > 18 and usg > 28 and apg < 2:
        tags.append("Half-Court Operator")
    if ppg > 14 and spg > 1.2:
        tags.append("Transition Threat")
    if is_guard and ppg > 14 and apg > 4:
        tags.append("Pick and Roll Ball Handler")
    if is_big and fg > fg_good and tpa < 2:
        tags.append("Pick and Roll Roller")
    if is_big and fg > fg_good and fta > 3 and tpa < 2:
        tags.append("Post Up Big")

    # ── Three-Point Profile ──────────────────────────────────────────────────
    if tp > 40 and tpa > 3:
        tags.append("Sniper")
    elif tpa > 7:
        tags.append("Volume Three Shooter")
    elif tpa > 8 and tp > 35:
        tags.append("Green Light")
    elif tpa < 3 and tp > 38:
        tags.append("Selective Shooter")
    elif tpa > 4 and 30 <= tp <= 34:
        tags.append("Streaky Shooter")
    elif 2 <= tpa <= 4 and 30 <= tp <= 35:
        tags.append("Developing Range")
    if tpa < 1 or (tp > 0 and tp < 25):
        tags.append("No Range")
    if usg < 20 and tp > 36 and apg < 2:
        tags.append("Catch-and-Shoot")
    if fg > 45 and tp < 28 and fga > 10:
        tags.append("Mid-Range Reliant")

    # ── Free Throw Profile ───────────────────────────────────────────────────
    if ft > 85:
        tags.append("Elite from the Line")
    if ft > 80 and fta > 4:
        tags.append("Clutch FT Upside")
    if fta > 6:
        tags.append("Gets to the Line")
    elif fta < 2 and fga > 8:
        tags.append("Avoids the Line")
    if fta > 6 and ft > 80:
        tags.append("Free Throw Merchant")

    # ── Passing Profile ──────────────────────────────────────────────────────
    if apg > 6 and ast_pct > 25:
        tags.append("Elite Passer")
    elif apg > 3 and not is_guard:
        tags.append("Willing Passer")
    if apg > 3 and tov_pct < 15:
        tags.append("Safe Passer")
    if apg > 5 and tov_pct > 20:
        tags.append("High Risk High Reward Passer")
    if apg > 5 and ppg < 10:
        tags.append("Pure Passer")
    if apg > 3 and ast_pct > 20 and tov_pct < 16:
        tags.append("Hockey Assist Type")
    if usg > 28 and apg > 5:
        tags.append("Ball Dominant")
    if apg < 1.5 and usg > 22:
        tags.append("Reluctant Passer")

    # ── Rebounding Profile ───────────────────────────────────────────────────
    if rpg > 10:
        tags.append("Elite Rebounder")
    elif rpg > 8:
        tags.append("Board Crasher")
    if is_guard and rpg > 5:
        tags.append("Guard Rebounder")
    if is_big and rpg < 4:
        tags.append("No Boards")
    if oreb > 3:
        tags.append("Offensive Crasher")
    elif oreb > 2.5:
        tags.append("Offensive Glass")
    if is_guard and rpg > 6:
        tags.append("Undersized Rebounder")
    if dreb > 5 and oreb < 1:
        tags.append("Box Out Type")
    if oreb > 2 and fga < 8:
        tags.append("Putback Specialist")

    # ── Efficiency ───────────────────────────────────────────────────────────
    if per > 25 and ts > 60:
        tags.append("Elite Efficiency")
    elif per > 18 and ts > 55:
        tags.append("Above Average Efficiency")
    elif per < 13:
        tags.append("Below Average Efficiency")
    if ts > 60 and efg > 55:
        tags.append("Ultra Efficient")
    if usg > 30 and ts < 50 and apg < 3:
        tags.append("Black Hole")

    # ── Usage Profile ────────────────────────────────────────────────────────
    if usg > 33:
        tags.append("Usage Monster")
    elif usg > 30:
        tags.append("Ball Dominant Creator")
    elif 22 <= usg <= 30:
        tags.append("Moderate Usage")
    if usg < 22 and bpm > 0:
        tags.append("Low Maintenance")
    if usg < 18 and bpm > 0:
        tags.append("Glue Guy")

    # ── Physical/Positional ──────────────────────────────────────────────────
    if ht > 0:
        if ht < _UNDERSIZED.get(pos, 0):
            tags.append("Undersized")
        elif ht > _PLUS_SIZE.get(pos, 999):
            tags.append("Plus Size")
    if is_big and ht > 0 and ht < 80 and apg > 2 and tp > 30:
        tags.append("Small Ball Five")
    # Positionless: stats don't fit typical position
    if is_big and apg > 4 and tp > 33:
        tags.append("Positionless")
    elif is_guard and rpg > 7 and bpg > 1:
        tags.append("Positionless")

    # ── Team Impact ──────────────────────────────────────────────────────────
    if ws > 4 and bpm > 4:
        tags.append("Winner")
    # Stat Stuffer: above average in 3+ categories
    above_avg = sum([ppg > 14, rpg > 6, apg > 4, spg > 1.2, bpg > 1])
    if above_avg >= 3:
        tags.append("Stat Stuffer")
    if ppg > 16 and bpm < 0 and ws < 2:
        tags.append("Empty Stats")
    if bpm > 5 and ppg > 16 and (spg + bpg) > 2:
        tags.append("Two-Way Star")
    if 4 <= len([x for x in [ppg, rpg, apg, spg, bpg] if x > 0]) >= 4:
        # Swiss Army Knife: decent contribution across many categories
        if ppg > 8 and rpg > 4 and apg > 2 and (spg > 0.8 or bpg > 0.8):
            tags.append("Swiss Army Knife")
    if ws > 3 and ppg < 10 and bpm > 0:
        tags.append("System Player")

    # ── Pace/Style ───────────────────────────────────────────────────────────
    if apg > 4 and spg > 1.2:
        tags.append("Pace Pusher")
    if mpg > 0 and mpg < 22 and per > 15:
        tags.append("Energy Guy")
    if mpg > 36 and gs > 20:
        tags.append("Iron Man")
    elif mpg > 35:
        tags.append("Workhorse")
    if mpg > 0 and mpg < 20 and per > 14:
        tags.append("Sixth Man")
    if gs > 0 and mpg > 0:
        # approximate: if GS is less than half expected games (~15 of 30)
        if gs < 15 and mpg > 15:
            tags.append("Bench Contributor")
    if mpg > 0 and mpg < 20 and per > 12:
        tags.append("Minutes Restricted")
    if ppg > 14 and mpg > 0 and mpg < 28:
        tags.append("Microwave Scorer")

    # ── Stamina/Durability ───────────────────────────────────────────────────
    if pf > 4:
        tags.append("Foul Trouble")
    elif pf > 3.5:
        tags.append("Foul Prone")

    # ── Draft Stock / NBA Readiness ──────────────────────────────────────────
    if is_young and rank <= 15 and per > 20:
        tags.append("One-and-Done Candidate")
    if is_young and per > 18:
        tags.append("High Upside")
    if rank <= 15 and bpm > 4:
        tags.append("Lottery Talent")
    if is_veteran and ws > 4:
        tags.append("Senior Leader")
    if is_young and ppg > 12 and tp < 30 and tov_pct > 20:
        tags.append("Raw Prospect")
    if is_veteran and ts > 55 and tov_pct < 18 and bpm > 0:
        tags.append("Pro Ready")
    if is_veteran and bpm > 0 and efg > 50:
        tags.append("High Floor")
    if is_young and usg > 25 and tov_pct > 22:
        tags.append("Boom or Bust")
    if rank > 45 and per > 20 and bpm > 3:
        tags.append("Second Round Steal")
    if bpm > 4 and ws40 > 0.15 and rank > 30:
        tags.append("Draft Riser")
    if per < 12 and bpm < 0 and rank > 100:
        tags.append("Undrafted Range")

    # ── Conference Context ───────────────────────────────────────────────────
    if conf in _POWER_CONFS and ppg > 14 and bpm > 2:
        tags.append("Power Conference Tested")
    if conf not in _POWER_CONFS and ppg > 20 and per > 22:
        tags.append("Conference Killer")

    # ═══════════════════════════════════════════════════════════════════════════
    # RED FLAGS
    # ═══════════════════════════════════════════════════════════════════════════

    if tov > 4 or tov_pct > 25:
        red_flags.append("Turnover Machine")
    elif tov > 3 or tov_pct > 20:
        red_flags.append("Turnover Prone")
    if pf > 3.5:
        red_flags.append("Foul Prone")
    if ft > 0 and ft < 55 and mpg > 20:
        red_flags.append("Hack-a-Player Risk")
    elif ft > 0 and ft < 65:
        red_flags.append("Poor FT Shooter")
    if ppg > 16 and bpm < -1 and ws < 1:
        red_flags.append("Empty Stats")
    if dbpm < -3 and spg < 0.5 and bpg < 0.3:
        red_flags.append("Defensive Liability")
    if usg > 28 and ts < 48:
        red_flags.append("Inefficient Volume")
    if is_big and rpg < 3:
        red_flags.append("No Boards")
    if tpa < 1 and is_guard:
        red_flags.append("Non-Shooter")
    if apg < 1 and usg > 25:
        red_flags.append("Ball Stopper")

    # Check one-dimensional
    strong_cats = sum([ppg > 16, rpg > 7, apg > 5, spg > 1.5, bpg > 1.5, tp > 38])
    weak_cats = sum([ppg < 8, rpg < 3, apg < 1.5])
    if strong_cats == 1 and weak_cats >= 2:
        red_flags.append("One-Dimensional")

    # Deduplicate tags (some conditions overlap)
    seen = set()
    unique_tags = []
    for t in tags:
        if t not in seen:
            seen.add(t)
            unique_tags.append(t)

    seen_rf = set()
    unique_rf = []
    for r in red_flags:
        if r not in seen_rf:
            seen_rf.add(r)
            unique_rf.append(r)

    return {
        "primary": primary,
        "defensive": defensive,
        "all_offensive": all_offensive,
        "all_defensive": all_defensive,
        "tags": unique_tags,
        "red_flags": unique_rf,
    }
