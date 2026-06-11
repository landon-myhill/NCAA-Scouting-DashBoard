#!/usr/bin/env python3
"""
tune.py — data-driven tuning of the draft-score blend against NBA outcomes
--------------------------------------------------------------------------
Optimizes the WEIGHTS in archetypes.combine_parts to maximize rank correlation
between our college score and BLENDED NBA VALUE (WS+VORP+tier percentile).

Honesty guard: leave-one-year-out cross-validation. For each held-out class we
tune on the OTHER three years and report correlation on the unseen year. A
change is only worth shipping if it lifts the held-out score, not just the
in-sample fit. The final shipped weights are then fit on all four years.

Usage:
    python -m analytics.tune    # report baseline + CV + propose tuned weights
"""

from analytics.backtest import load_matched, attach_value_target, spearman, MATURE_YEARS
from model.archetypes import draft_score, combine_parts, DEFAULT_WEIGHTS

# Search bounds per weight: (low, high). Component blend weights are bounded so
# no single block dominates; bonus scalars and damps get wider latitude.
BOUNDS = {
    "prod": (0.0, 0.60), "eff": (0.0, 0.60), "impact": (0.0, 0.60), "two_way": (0.0, 0.40),
    "play": (0.0, 3.0), "ft": (0.0, 3.0), "min": (0.0, 4.0), "tov": (0.0, 3.0),
    "size": (0.0, 3.0), "anthro": (0.0, 3.0), "elite": (0.0, 3.0), "recruit": (0.0, 3.0),
    "age_damp": (0.0, 2.5), "conf_damp": (0.0, 2.0), "pos_damp": (0.0, 2.5),
}


def precompute(rows):
    """Score parts once per player; tuning then only re-blends (fast)."""
    return [(draft_score(r["college_record"], return_parts=True), r["target"], r["year"]) for r in rows]


def score_weights(cache, weights, years=None):
    """Pooled Spearman of combine_parts(weights) vs target over the given years."""
    xs, ts = [], []
    for parts, tgt, yr in cache:
        if years is not None and yr not in years:
            continue
        xs.append(combine_parts(parts, weights))
        ts.append(tgt)
    return spearman(xs, ts)


def _objective(cache, weights, years, reg):
    """Regularized objective: rho minus L2 penalty on relative drift from defaults.
    The penalty is what stops a 15-knob search from memorizing ~189 points."""
    rho = score_weights(cache, weights, years)
    if rho is None:
        return None
    pen = 0.0
    for k, base in DEFAULT_WEIGHTS.items():
        if base:
            pen += ((weights[k] - base) / base) ** 2
    return rho - reg * pen


def coordinate_ascent(cache, train_years, start=None, rounds=40, reg=0.012, knobs=None):
    """Greedy hill-climb maximizing the REGULARIZED objective over train_years.
    knobs: subset of weights allowed to move (None = all in BOUNDS)."""
    w = dict(start or DEFAULT_WEIGHTS)
    movable = list(knobs) if knobs else list(BOUNDS)
    best = _objective(cache, w, train_years, reg)
    steps = [1.6, 1.3, 1.15, 1.07]  # multiplicative; also try additive near 0
    for _ in range(rounds):
        improved = False
        for k in movable:
            lo, hi = BOUNDS[k]
            for factor in steps:
                for cand in (w[k] * factor, w[k] / factor, w[k] + 0.05, w[k] - 0.05):
                    cand = max(lo, min(hi, round(cand, 4)))
                    if cand == w[k]:
                        continue
                    trial = dict(w); trial[k] = cand
                    r = _objective(cache, trial, train_years, reg)
                    if r is not None and r > best + 1e-6:
                        w, best, improved = trial, r, True
        if not improved:
            break
    return w, score_weights(cache, w, train_years)


# The prior hand-tuned blend, kept as the honest comparison baseline.
OLD_WEIGHTS = {
    "prod": 0.27, "eff": 0.28, "impact": 0.25, "two_way": 0.10,
    "play": 1.0, "ft": 1.0, "min": 1.0, "tov": 1.0,
    "size": 1.0, "anthro": 1.0, "elite": 1.0, "recruit": 1.0,
    "age_damp": 1.0, "conf_damp": 1.0, "pos_damp": 1.0,
}

# ── Shipped methodology: ridge-fit hybrid ────────────────────────────────────
# Ridge-fit a linear blend of the real-signal components, then scale by the
# original conference/age/position multipliers (kept multiplicative for
# full-board sanity). 'min'/'tov' are degenerate guard features — held fixed,
# not fit. This is what produced archetypes.DEFAULT_WEIGHTS.
HYBRID_FIT = ["prod", "eff", "impact", "two_way", "play", "ft",
              "size", "anthro", "elite", "recruit"]
HYBRID_GUARD = {"min": 0.8, "tov": 0.8}  # fixed scalars
HYBRID_LAMBDA = 150.0
HYBRID_SCALE = 400.0  # ranking-invariant; just makes weights readable


def fit_hybrid(cache, train_years=None, lam=HYBRID_LAMBDA):
    """Ridge-fit the hybrid blend; returns a full weights dict for combine_parts."""
    import numpy as np
    sel = [(p, t) for p, t, y in cache if train_years is None or y in train_years]
    X = np.array([[p[k] for k in HYBRID_FIT] for p, _ in sel], float)
    y = np.array([t for _, t in sel], float)
    mu, sd = X.mean(0), X.std(0) + 1e-9
    Xs = (X - mu) / sd
    b = y - y.mean()
    coef = np.linalg.solve(Xs.T @ Xs + lam * np.eye(Xs.shape[1]), Xs.T @ b)
    w = {k: round(float(c / s) * HYBRID_SCALE, 4) for k, c, s in zip(HYBRID_FIT, coef, sd)}
    w.update(HYBRID_GUARD)
    w.update(age_damp=1.0, conf_damp=1.0, pos_damp=1.0)
    return w


def cv_hybrid(cache):
    """Leave-one-year-out held-out Spearman for the shipped hybrid recipe."""
    outs = {}
    for hold in MATURE_YEARS:
        w = fit_hybrid(cache, [y for y in MATURE_YEARS if y != hold])
        xs = [combine_parts(p, w) for p, t, y in cache if y == hold]
        ts = [t for p, t, y in cache if y == hold]
        outs[hold] = spearman(xs, ts)
    return outs


LINEAR_FEATURES = ["prod", "eff", "impact", "two_way", "play", "ft", "min",
                   "tov", "size", "anthro", "elite", "recruit",
                   "age_mult", "conf_mult", "pos_mult"]


def fit_linear_model(cache, train_years=None, lam=80.0):
    """Ridge-fit a linear blend of the score parts against the target.
    Returns {feature: weight} where weight = coef/sd (so score = sum w*feature).
    The intercept/target-mean are dropped — they don't affect ranking."""
    import numpy as np
    sel = [(p, t) for p, t, y in cache if train_years is None or y in train_years]
    X = np.array([[p[k] for k in LINEAR_FEATURES] for p, _ in sel], float)
    y = np.array([t for _, t in sel], float)
    mu, sd = X.mean(0), X.std(0) + 1e-9
    Xs = (X - mu) / sd
    b = y - y.mean()
    coef = np.linalg.solve(Xs.T @ Xs + lam * np.eye(Xs.shape[1]), Xs.T @ b)
    return {k: float(c / s) for k, c, s in zip(LINEAR_FEATURES, coef, sd)}


def linear_score(parts, model):
    return sum(w * parts[k] for k, w in model.items())


def cv_linear(cache, lam=80.0):
    """Leave-one-year-out held-out Spearman for the ridge linear model."""
    outs = {}
    for hold in MATURE_YEARS:
        train = [y for y in MATURE_YEARS if y != hold]
        m = fit_linear_model(cache, train, lam)
        xs = [linear_score(p, m) for p, t, y in cache if y == hold]
        ts = [t for p, t, y in cache if y == hold]
        outs[hold] = spearman(xs, ts)
    return outs


def main():
    rows = load_matched()
    attach_value_target(rows)
    cache = precompute(rows)
    print(f"n = {len(rows)} matched drafted players, years {MATURE_YEARS}")
    print("Objective: rank correlation between college score and BLENDED NBA VALUE")
    print("(career WS + VORP + tier percentile). Honest test = leave-one-year-out.\n")

    # ── Held-out CV: old hand-tuned vs shipped ridge hybrid ──────────────────
    print("Leave-one-year-out held-out Spearman:")
    print(f"  {'year':>6}  {'old-hand':>9}  {'ridge-hybrid':>12}")
    old_cv, hyb = [], cv_hybrid(cache)
    for hold in MATURE_YEARS:
        oh = score_weights(cache, OLD_WEIGHTS, [hold])
        old_cv.append(oh)
        print(f"  {hold:>6}  {oh:>+9.3f}  {hyb[hold]:>+12.3f}")
    ocv = sum(old_cv) / len(old_cv); hcv = sum(hyb.values()) / len(hyb)
    print(f"  {'MEAN':>6}  {ocv:>+9.3f}  {hcv:>+12.3f}   (held-out gain {hcv-ocv:+.3f})")

    # ── Shipped weights (fit on all mature years) ───────────────────────────
    w_final = fit_hybrid(cache, None)
    print("\nShipped weights (ridge hybrid, fit on all years) — now in archetypes.py:")
    for k in HYBRID_FIT:
        print(f"    {k:10s} {w_final[k]:+.4f}")
    print(f"    (min/tov fixed guards = {HYBRID_GUARD}; multipliers kept at damp=1.0)")

    note = "ships" if hcv > ocv else "NO held-out gain — do not ship"
    print(f"\nVerdict: ridge hybrid {note} ({hcv-ocv:+.3f} held-out).")
    print("Note: gains are modest — the formula is near the ceiling of these")
    print("features. Bigger lifts need NEW inputs (true age, SOS, shot location)")
    print("or fixing selection bias (add undrafted/mid-major NBA outcomes).")


if __name__ == "__main__":
    main()
