"""
NCAA Draft Scout — Player Archetype Classification & Draft Scoring
-------------------------------------------------------------------
Classifies players into archetypes and tags based on their stats.
Provides composite draft scoring for realistic draft board ranking.
"""


def _s(stats: dict, key: str, default=0) -> float:
    """Safely get a stat value, defaulting to 0."""
    v = stats.get(key)
    return v if v is not None else default


def _height_inches(height: str) -> int:
    """Convert height string like 6'9\" or 6-9 to total inches."""
    try:
        if "'" in height:
            parts = height.replace('"', '').split("'")
            return int(parts[0]) * 12 + int(parts[1])
        if "-" in height:
            parts = height.split("-")
            return int(parts[0]) * 12 + int(parts[1])
    except (ValueError, IndexError):
        pass
    return 0


# ── Position height thresholds (inches) ──────────────────────────────────────

_UNDERSIZED = {"G": 73, "F": 77, "C": 81}
_PLUS_SIZE  = {"G": 76, "F": 80, "C": 84}
_POWER_CONFS = {"ACC", "SEC", "Big Ten", "Big 12", "Big East", "Pac-12"}


# ── Age/class year draft value multiplier ────────────────────────────────────
_CLASS_BONUS = {
    "Freshman": 1.22,
    "Sophomore": 1.10,
    "Junior": 1.0,
    "Senior": 0.85,
    "Graduate": 0.76,
    "5th Year": 0.70,
    "Unknown": 0.95,
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


def draft_score(player: dict) -> float:
    """
    Compute a composite draft score for ranking players.

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
    pos = player.get("pos", "")
    is_g = pos == "G"
    is_c = pos == "C"
    if is_g:
        ppg_cap, rpg_cap, apg_cap = 23.0, 6.0, 8.0
    elif is_c:
        ppg_cap, rpg_cap, apg_cap = 19.0, 12.0, 4.0
    else:  # SF, PF, F
        ppg_cap, rpg_cap, apg_cap = 23.0, 9.0, 5.0

    prod = (
        min(ppg / ppg_cap, 1.0) * 50 +    # scoring
        min(rpg / rpg_cap, 1.0) * 15 +    # rebounding
        min(apg / apg_cap, 1.0) * 25 +    # playmaking
        min(spg / 2.5, 1.0) * 10 +        # steals
        min(bpg / 2.5, 1.0) * 10          # blocks
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
    if efg > 0:
        eff += min((efg - 35) / 25.0, 1.0) * 12  # eFG% (raised)
    # Shooting: FG% and 3P%
    if fg_pct > 0:
        eff += min((fg_pct - 35) / 25.0, 1.0) * 6    # FG% (lowered)
    # 3P% — guards/wings weighted heavy, centers low (not expected to shoot)
    if tp_pct > 0 and tpa > 1:
        tp_weight = 6 if is_c else 22
        eff += min((tp_pct - 25) / 15.0, 1.0) * tp_weight
    # Usage-efficiency bonus: high usage + high TS% = shot creator
    if usg > 24 and ts > 56:
        eff += min((usg - 24) / 10.0, 1.0) * 20

    # ── Impact score (0-100 scale) ───────────────────────────────────────────
    impact = 0
    if ws > 0:
        impact += min(ws / 7.0, 1.0) * 60       # Win Shares
    if ws40 > 0:
        impact += min(ws40 / 0.25, 1.0) * 40    # WS/40

    # ── Two-way score (0-100 scale) ──────────────────────────────────────────
    two_way = 0
    if dbpm != 0:
        two_way += min((dbpm + 3) / 8.0, 1.0) * 40   # DBPM
    if dws > 0:
        two_way += min(dws / 3.0, 1.0) * 30           # DWS
    two_way += min((spg + bpg) / 3.5, 1.0) * 30       # stocks

    # ── Playmaking bonus (guards who create for others) ──────────────────────
    ast_pct = _s(a, "AST%")
    play_bonus = 0
    if apg > 4 and ast_pct > 20:
        play_bonus = min((apg - 4) / 5.0, 1.0) * 5

    # ── Minutes bonus/penalty ────────────────────────────────────────────────
    mpg = _s(s, "MPG")
    min_bonus = 0
    if mpg >= 34:
        min_bonus = 4       # starter, heavy minutes
    elif mpg >= 30:
        min_bonus = 2       # solid starter
    elif mpg >= 25:
        min_bonus = 0       # rotation player
    elif mpg > 0:
        min_bonus = -3      # limited minutes, stats inflated

    # ── Turnover penalty ─────────────────────────────────────────────────────
    tov_pen = 0
    if tov > 3:
        tov_pen += (tov - 3) * 2
    if tov_pct > 20:
        tov_pen += (tov_pct - 20) * 0.5

    # ── Free throw bonus (NBA values getting to the line efficiently) ────────
    ft_bonus = 0
    if fta > 5 and _s(s, "FT%") > 75:
        ft_bonus = 3

    # ── Weighted composite ───────────────────────────────────────────────────
    raw = (
        prod * 0.38 +
        eff * 0.25 +
        impact * 0.15 +
        two_way * 0.10 +
        play_bonus +
        ft_bonus +
        min_bonus -
        tov_pen
    )

    # ── Multipliers ──────────────────────────────────────────────────────────
    year = player.get("year", "Unknown")
    conf = player.get("conference", "")

    age_mult = _CLASS_BONUS.get(year, 0.95)
    conf_mult = _CONF_MULTIPLIER.get(conf, 0.93)
    pos_mult = _POS_VALUE.get(pos, 1.0)

    # ── Size bonus (reduced — only for 6'10"+) ──────────────────────────────
    # ── Height bonus/penalty (position-relative, per inch from average) ─────
    # Average heights: PG=75(6'3"), SG=77(6'5"), SF=79(6'7"), PF=81(6'9"), C=83(6'11")
    _POS_AVG_HT = {"G": 75, "F": 80, "C": 83}
    ht = _height_inches(player.get("height", ""))
    avg_ht = _POS_AVG_HT.get(pos, 79)
    size_bonus = 0
    if ht > 0:
        diff = ht - avg_ht  # positive = taller than avg for position
        if diff >= 3:
            size_bonus = 3.5
        elif diff >= 2:
            size_bonus = 2.0
        elif diff >= 1:
            size_bonus = 1.0
        elif diff <= -3:
            size_bonus = -8.0
        elif diff <= -2:
            size_bonus = -5.0
        elif diff <= -1:
            size_bonus = -2.5

    final = (raw * age_mult * conf_mult * pos_mult) + size_bonus

    return round(final, 2)


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
        if fg > 55 and ppg > 14 and fta > 3:
            all_offensive.append("Post Scorer")
        if rpg > 8 and oreb > 2:
            all_offensive.append("Glass Cleaner")
        if fg > 55 and tpa < 1 and rpg > 8:
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
    if dbpm < -2 and spg < 0.5 and bpg < 0.3:
        all_defensive.append("Defensive Liability")

    # Suppress overlaps:
    # - Defensive Anchor suppresses Paint Presence and Weak Side Shot Blocker
    # - Defensive Liability is exclusive (can't also be No Defense)
    _def_set = set(all_defensive)
    if "Defensive Anchor" in _def_set:
        all_defensive = [a for a in all_defensive if a not in ("Paint Presence", "Weak Side Shot Blocker")]
    if "Defensive Liability" not in _def_set and dbpm < 0 and spg < 0.5 and bpg < 0.3:
        all_defensive.append("No Defense")

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
    if fg > 58 and tpa < 2 and fta > 3:
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
    if is_big and fg > 55 and tpa < 2:
        tags.append("Pick and Roll Roller")
    if is_big and fg > 55 and fta > 3 and tpa < 2:
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
