"""Human copy shown in the UI: score-component explainers, tier labels,
archetype descriptions. No logic — just text kept next to the keys it
describes so the explainer can never disagree with the actual formula."""

# Ordered for display. label/desc are human copy; `key` indexes DEFAULT_WEIGHTS
# and the parts dict from draft_score(return_parts=True).
SCORE_COMPONENTS = [
    {"key": "recruit", "label": "Recruit Pedigree", "color": "#f472b6",
     "desc": "HS recruit ranking. The single strongest predictor of NBA success."},
    {"key": "elite", "label": "Elite Metrics", "color": "#22d3ee",
     "desc": "Bonuses for elite BPM / PER / WS-40 (position-adjusted thresholds)."},
    {"key": "two_way", "label": "Two-Way", "color": "#8b5cf6",
     "desc": "Defensive value: DBPM, DWS, stocks (steals + blocks)."},
    {"key": "size", "label": "Size", "color": "#a3e635",
     "desc": "Height relative to position average."},
    {"key": "impact", "label": "Impact", "color": "#10b981",
     "desc": "Winning contribution: Win Shares and WS/40."},
    {"key": "anthro", "label": "Length", "color": "#fb923c",
     "desc": "Combine wingspan and hand size (when measured)."},
    {"key": "play", "label": "Playmaking", "color": "#60a5fa",
     "desc": "Bonus for high assist rate and rare big-man creation."},
    {"key": "prod", "label": "Production", "color": "#f59e0b",
     "desc": "Per-36 PPG/RPG/APG/SPG/BPG vs position-specific caps."},
    {"key": "ft", "label": "Free Throw", "color": "#94a3b8",
     "desc": "FT% as a touch/translation signal."},
    {"key": "eff", "label": "Efficiency", "color": "#3b82f6",
     "desc": "PER/TS%/eFG%/shooting. Data-fit weight is slightly NEGATIVE — "
             "pure college efficiency adds noise, not NBA signal, once the rest is in."},
    {"key": "min", "label": "Minutes Guard", "color": "#64748b",
     "desc": "Small penalty for <15 MPG samples (too noisy to trust)."},
    {"key": "tov", "label": "Turnover Penalty", "color": "#ef4444",
     "desc": "Penalty scaling with turnover rate."},
]
SCORE_COMPONENT_KEYS = [c["key"] for c in SCORE_COMPONENTS]

SCORE_METHODOLOGY = {
    "summary": ("Component scores are blended with weights fit by ridge "
                "regression against real NBA career value (Win Shares + VORP + "
                "tier) on the 2020-2023 draft classes, then scaled by "
                "conference / class-year / position multipliers."),
    "validation": ("Validated with leave-one-year-out cross-validation: "
                   "held-out rank correlation vs NBA value +0.358 "
                   "(the prior hand-tuned formula scored +0.339)."),
    "projection": ("On top of the ranking, an ML layer (analytics/predict.py) adds "
                   "Boom/Bust probabilities per player: Boom calibrates the draft "
                   "score into P(NBA starter or better) — held-out AUC 0.70 — and "
                   "Bust is a separate logistic model on the score components that "
                   "spots downside risk the rank can't see (held-out AUC 0.73). "
                   "Probabilities assume a drafted-caliber prospect."),
}

TIER_LABELS = {1: "Tier 1 — Lottery", 2: "Tier 2 — Late 1st", 3: "Tier 3 — 2nd Round"}

ARCHETYPE_DESCRIPTIONS = {
    "Elite Floor General": "A top-tier point guard who controls tempo, creates for others at elite rates, and limits turnovers. Think Chris Paul — high AST%, low TOV%, efficient scoring.",
    "Floor General": "A strong facilitator who runs the offense and gets teammates involved. Solid assist numbers and court vision, but may lack the elite efficiency or turnover discipline of the top tier.",
    "Scoring Guard": "A high-usage backcourt scorer who can create his own shot consistently. Lives above 18 PPG with heavy usage — the go-to option in half-court sets.",
    "3-and-D Guard": "A two-way guard who spaces the floor with reliable three-point shooting and disrupts passing lanes on defense. Low usage, high impact.",
    "Combo Guard": "A versatile backcourt player who can score and distribute. Blends scoring punch (14+ PPG) with real playmaking (4+ APG).",
    "Three-Level Scorer": "An elite offensive weapon who can score from all three levels — at the rim, from mid-range, and behind the arc. The most translatable offensive archetype.",
    "Two-Way Star": "A dominant player who impacts both ends at a high level. Elite production combined with real defensive stats and a strong BPM. Franchise-caliber prospects.",
    "Two-Way Wing": "A wing who contributes on both ends without being elite at either. Good combination of scoring and defensive activity. Versatile rotation player.",
    "Sharpshooter": "A lights-out three-point specialist who stretches defenses. Shoots 37%+ on high volume from deep. Floor spacing is an increasingly valuable skill.",
    "Point Forward": "A forward with legitimate playmaking ability. Creates for others from the high post or in transition — a mismatch weapon. Rare and highly valued.",
    "Stretch Five": "A center who can step out and shoot threes while still protecting the rim. Floor spacing from the five spot with shot-blocking upside. Extremely scarce.",
    "Modern Big": "A versatile big man who can pass, shoot, and operate in space. Can facilitate from the elbow and hit open threes. The new prototype for big men.",
    "Post Scorer": "An efficient interior scorer who dominates in the paint with touch and footwork. High FG%, gets to the line, and finishes through contact.",
    "Glass Cleaner": "A dominant rebounder who controls the glass on both ends. Elite rebounding with strong offensive rebounding. Creates extra possessions.",
    "Old School Big": "A traditional center who operates exclusively in the paint. High FG% but no three-point range. Limited in modern spread offenses.",
    "Small Ball Five": "An undersized big who plays bigger than his height. Can shoot, pass, and switch on defense — the positionless basketball prototype.",
    "Volume Scorer": "A high-usage scorer who puts up big numbers through volume. 18+ PPG with heavy usage — can be a go-to option if efficiency develops.",
    "Secondary Scorer": "A capable scorer who thrives as a second or third option. Solid production without needing the ball constantly. Fits next to a primary creator.",
    "Playmaker": "A pass-first player who creates for teammates as his primary skill. Strong assist numbers — may not score much, but makes the offense run.",
    "Rebounder": "A player whose primary contribution is controlling the glass. Elite rebounding but limited offensive creation. Effective in the right system.",
    "Rim Protector": "A shot-blocking specialist who deters attacks at the rim. 1.5+ BPG — his defensive presence is his calling card.",
    "Role Player": "A player without a standout skill that defines his game. Solid but unspectacular. Can contribute in a specific role but likely needs development.",
    "Defensive Anchor": "An elite rim protector who anchors the entire defense. 2+ BPG with strong defensive win shares and BPM. Franchise-level defensive impact.",
    "Point of Attack Defender": "A guard who can lock up the opposing team's best ball handler. Active hands, positive defensive BPM, and quickness to stay in front.",
    "Perimeter Pest": "An aggressive perimeter defender who disrupts the offense with constant ball pressure. Gets steals and deflections but may gamble too much.",
    "Wing Stopper": "A versatile wing defender who can guard 2-4 positions. Combines steals, blocks, and positive defensive metrics — the modern switch-everything defender.",
    "Versatile Defender": "A defender who can guard multiple positions and contribute stocks across the board. Active in passing lanes and at the rim.",
    "Paint Presence": "A big man who deters shots at the rim with size and timing. 1.5+ BPG — changes the math on drives and interior passes.",
    "Weak Side Shot Blocker": "A rim protector who gets blocks primarily as a help defender. 2+ BPG but low steal numbers.",
    "Help Defender": "A positional defender who cleans up on the weak side. Good rebounding and some shot-blocking, but not an on-ball stopper.",
    "Defensive Liability": "A player with significant defensive limitations. Negative DBPM, low stocks — gets targeted by opposing offenses.",
    "No Defense": "A player who provides minimal defensive contribution. Low stocks and negative or flat defensive metrics. Must be hidden defensively.",
    "Average Defender": "A player whose defense is neither a strength nor a weakness. Does enough to stay on the floor. Neutral defensive impact.",
}
