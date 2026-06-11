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
    # v2 vocabulary — every archetype is a strength-recipe; players get fit
    # percentiles on all applicable archetypes (see model/strengths.py).
    "Floor General": "Playmaking-dominant lead guard: runs the offense, creates for others, protects the ball.",
    "Scoring Guard": "Scoring-dominant guard: shot-making volume with shooting and finishing behind it.",
    "Combo Guard": "Scoring and playmaking both strong, neither dominant — can run the offense or play off it.",
    "Slasher": "A downhill attacker who lives in the paint and at the line. High rim pressure, strong interior finishing. Creates offense with force, not jumpers.",
    "Sharpshooter": "Shooting-dominant: high-volume, high-accuracy three-point shooting with free-throw touch.",
    "Stretch Big": "A forward/center whose shooting is the headline skill — the rarest, most valuable big-man trait.",
    "Three-Level Scorer": "Scoring, shooting, AND finishing all high — the premium offensive label; the most translatable scorer type.",
    "Connector": "The modern glue wing: no dominant skill, but above-average passing, ball security, and defense at low usage. Makes the right play, never needs the ball.",
    "Offensive Hub": "A big who runs offense through himself — elbow touches, handoffs, post splits. Elite passing for his size plus real scoring gravity.",
    "Post Scorer": "Interior-scoring big: high-efficiency paint scoring (graded against his shot diet) with rim pressure and rebounding.",
    "Play Finisher": "A vertical-spacer big who converts what others create — lobs, rolls, dump-offs — with elite finishing and rim protection, without needing post touches.",
    "Glass Cleaner": "Rebounding-dominant (measured on the absolute scale): controls the glass, creates extra possessions.",
    "Switch Defender": "Elite at BOTH ends of the defensive spectrum: guards the perimeter and protects the rim. The rarest defensive profile in the switch-everything era.",
    "Rim Protector": "Shot-blocking and interior deterrence (absolute scale), backed by size and defensive rebounding.",
    "Point-of-Attack Defender": "A guard who pressures the ball: steals, deflections, and positive defensive impact at the point of attack.",
    "Wing Stopper": "A forward/wing whose perimeter defense is elite on the absolute scale — guards multiple positions with real length.",
    "Average Defender": "Defense is neither a strength nor a weakness — does enough to stay on the floor.",
    "Defensive Liability": "Both defensive strengths grade out near the bottom of the class — must be hidden defensively.",
}
