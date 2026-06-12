#!/usr/bin/env python3
"""
analytics.predict — Boom/Bust probabilities, calibrated on the STRENGTHS
MODEL (the actual ranking), not the retired formula.

Boom = P(NBA starter or better), Bust = P(bench or out of the league),
learned from the eligible 2020-23 classes. Each is a 50/50 blend of a
logistic and a binned-empirical (isotonic) calibration of the strengths-
model score — smooth differentiation with honest tails; in LOYO CV the
strengths model is REFIT per fold so the held-out AUC is honest (no
peeking at the held-out year through the ranking model).

Usage:
    python -m analytics.predict            # validate + stamp the class pool
    python -m analytics.predict --dry-run  # validate only
"""

import sys

import numpy as np

from analytics.backtest import MATURE_YEARS, attach_value_target, load_matched
from analytics.strengths_model import (FEATURE_SETS, _design, _fit_ridge,
                                       _predict as _sm_predict)
from core import PLAYERS_FILE, load_json, save_json
from model.strengths import compute_fits, compute_strengths

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

SUCCESS_MIN_TIER = 3   # starter or star
STAR_MIN_TIER = 4      # star only
BUST_MAX_TIER = 1      # bench or never made it
FEATS = FEATURE_SETS["inter+market+conf"]  # keep in lockstep with strengths_model
LAMBDA_RIDGE = 20.0
LAMBDA_LOGIT = 1.0


def _sigmoid(z):
    return 1.0 / (1.0 + np.exp(-np.clip(z, -30, 30)))


def fit_isotonic(x, y, min_bin=25):
    """Monotone calibration on quantile bins of >=min_bin players each, then
    PAVA. Probabilities equal empirical rates and can never be more extreme
    than a full bin supports — the logistic's saturated tails claimed 1%
    bust where history says 4%, and raw per-point PAVA claimed 0%."""
    order = np.argsort(x)
    xs = np.asarray(x, float)[order]
    vals = np.asarray(y, float)[order]
    n = len(xs)
    n_bins = max(2, n // min_bin)
    edges = [round(i * n / n_bins) for i in range(n_bins + 1)]
    grid = [float(np.mean(xs[a:b])) for a, b in zip(edges, edges[1:])]
    means = [float(np.mean(vals[a:b])) for a, b in zip(edges, edges[1:])]
    weights = [float(b - a) for a, b in zip(edges, edges[1:])]
    # PAVA over the bins
    out_m, out_w, out_x = [], [], []
    for g, m, w in zip(grid, means, weights):
        out_m.append(m); out_w.append(w); out_x.append(g)
        while len(out_m) > 1 and out_m[-2] >= out_m[-1]:
            m2, w2 = out_m.pop(), out_w.pop(); x2 = out_x.pop()
            out_m[-1] = (out_m[-1] * out_w[-1] + m2 * w2) / (out_w[-1] + w2)
            out_x[-1] = (out_x[-1] * out_w[-1] + x2 * w2) / (out_w[-1] + w2)
            out_w[-1] += w2
    return {"x": out_x, "p": out_m}


def iso_prob(c, x):
    return np.clip(np.interp(np.asarray(x, float), c["x"], c["p"]), 0.0, 1.0)


def fit_logistic_1d(x, y, lam=LAMBDA_LOGIT, iters=25):
    """1-D logistic calibration: returns (a, b) for sigmoid(a*x_std + b)."""
    mu, sd = float(np.mean(x)), float(np.std(x)) + 1e-9
    xs = (np.asarray(x) - mu) / sd
    A = np.column_stack([np.ones_like(xs), xs])
    bvec = np.zeros(2)
    reg = np.diag([0.0, lam])
    for _ in range(iters):
        p = _sigmoid(A @ bvec)
        W = np.clip(p * (1 - p), 1e-6, None)
        H = A.T @ (A * W[:, None]) + reg
        g = A.T @ (y - p) - reg @ bvec
        step = np.linalg.solve(H, g)
        bvec += step
        if np.max(np.abs(step)) < 1e-8:
            break
    return {"b0": float(bvec[0]), "b1": float(bvec[1]), "mu": mu, "sd": sd}


def calib_prob(c, x):
    return _sigmoid(c["b0"] + c["b1"] * ((np.asarray(x) - c["mu"]) / c["sd"]))


def auc(y_true, scores) -> float:
    pos = [s for s, t in zip(scores, y_true) if t == 1]
    neg = [s for s, t in zip(scores, y_true) if t == 0]
    if not pos or not neg:
        return float("nan")
    wins = sum((p > n) + 0.5 * (p == n) for p in pos for n in neg)
    return wins / (len(pos) * len(neg))


def _prep(rows):
    """Stamp class-relative strengths + market on the training rows."""
    for yr in sorted({r["year"] for r in rows}):
        recs = [r["college_record"] for r in rows if r["year"] == yr]
        compute_strengths(recs, reference=recs)
        compute_fits(recs, reference=recs)
    for r in rows:
        r["college_record"]["_market_rank"] = r["pick"]


def _labels(rows):
    ys = np.array([1.0 if r["tier_val"] >= SUCCESS_MIN_TIER else 0.0 for r in rows])
    yb = np.array([1.0 if r["tier_val"] <= BUST_MAX_TIER else 0.0 for r in rows])
    yst = np.array([1.0 if r["tier_val"] >= STAR_MIN_TIER else 0.0 for r in rows])
    return ys, yb, yst


def loyo_cv(rows):
    """Held-out AUC per year; the strengths model is refit per fold."""
    rows = [r for r in rows if r.get("target") is not None] or rows
    attach_value_target(rows)
    rows = [r for r in rows if r.get("target") is not None]
    _prep(rows)
    recs = [r["college_record"] for r in rows]
    X = _design(recs, FEATS)
    yv = np.array([r["target"] for r in rows], float)
    ys, yb, yst = _labels(rows)
    years = np.array([r["year"] for r in rows])
    out = {}
    for hold in MATURE_YEARS:
        tr, te = years != hold, years == hold
        if te.sum() < 5:
            continue
        m = _fit_ridge(X[tr], yv[tr], LAMBDA_RIDGE)
        s_tr, s_te = _sm_predict(m, X[tr]), _sm_predict(m, X[te])
        cs, cls = fit_isotonic(s_tr, ys[tr]), fit_logistic_1d(s_tr, ys[tr])
        cb, clb = fit_isotonic(-s_tr, yb[tr]), fit_logistic_1d(-s_tr, yb[tr])
        cst, clst = fit_isotonic(s_tr, yst[tr]), fit_logistic_1d(s_tr, yst[tr])
        out[hold] = {
            "auc_success": auc(ys[te], 0.5*iso_prob(cs, s_te) + 0.5*calib_prob(cls, s_te)),
            "auc_bust": auc(yb[te], 0.5*iso_prob(cb, -s_te) + 0.5*calib_prob(clb, -s_te)),
            "auc_star": auc(yst[te], 0.5*iso_prob(cst, s_te) + 0.5*calib_prob(clst, s_te)),
            "n": int(te.sum()),
        }
    return out


class Head:
    """Calibrated head: strengths-model score -> probability.

    50/50 blend of two calibrations: logistic (smooth — differentiates the
    top of the board) and binned-empirical isotonic (honest — tails can't
    drift below what a full bin of history supports)."""

    def __init__(self, ridge, iso, logi, flip=False):
        self.ridge, self.iso, self.logi, self.flip = ridge, iso, logi, flip

    def prob(self, records):
        s = _sm_predict(self.ridge, _design(records, FEATS))
        x = -s if self.flip else s
        return 0.5 * iso_prob(self.iso, x) + 0.5 * calib_prob(self.logi, x)


def train_final(rows):
    rows = [r for r in rows if r.get("target") is not None] or rows
    attach_value_target(rows)
    rows = [r for r in rows if r.get("target") is not None]
    _prep(rows)
    recs = [r["college_record"] for r in rows]
    X = _design(recs, FEATS)
    yv = np.array([r["target"] for r in rows], float)
    ys, yb, yst = _labels(rows)
    m = _fit_ridge(X, yv, LAMBDA_RIDGE)
    s = _sm_predict(m, X)
    return (Head(m, fit_isotonic(s, ys), fit_logistic_1d(s, ys)),
            Head(m, fit_isotonic(-s, yb), fit_logistic_1d(-s, yb), flip=True),
            Head(m, fit_isotonic(s, yst), fit_logistic_1d(s, yst)))


def main():
    dry = "--dry-run" in sys.argv
    rows = load_matched(years=(2020, 2021, 2022, 2023, 2024, 2025), include_undrafted=True)  # young classes join training (held-out unchanged)
    attach_value_target(rows)
    rows = [r for r in rows if r.get("target") is not None]
    ys, yb, yst = _labels(rows)
    print(f"Training pool: {len(rows)} eligible players "
          f"(star {int(yst.sum())}, success {int(ys.sum())}, bust {int(yb.sum())})")

    cv = loyo_cv(rows)
    print("\nLeave-one-year-out held-out AUC (strengths-model calibration):")
    for y, m in cv.items():
        print(f"  {y}: star {m['auc_star']:.3f}  success {m['auc_success']:.3f}  "
              f"bust {m['auc_bust']:.3f}  (n={m['n']})")
    print(f"  MEAN: star {np.nanmean([m['auc_star'] for m in cv.values()]):.3f}  "
          f"success {np.mean([m['auc_success'] for m in cv.values()]):.3f}  "
          f"bust {np.mean([m['auc_bust'] for m in cv.values()]):.3f}"
          "   (star mean skips folds whose class produced no NCAA star)")
    if dry:
        return

    # Stamp the current class pool (only pool players have model features)
    head_s, head_b, head_st = train_final(rows)
    from web import store  # pool already has strengths + mock stamped
    pool, _, _ = store.board_filter(store.PLAYERS, store.CURRENT_SEASON_YEAR,
                                    with_stubs=False)
    ps, pb, pst = head_s.prob(pool), head_b.prob(pool), head_st.prob(pool)
    raw = load_json(PLAYERS_FILE)
    by_id = {p["id"]: p for p in raw["players"]}
    stamped = 0
    for p, s, b, st in zip(pool, ps, pb, pst):
        rec = by_id.get(p["id"])
        if rec is not None:
            s, b, st = float(s), float(b), float(st)
            st = min(st, s)                    # star ⊆ success (ordered tiers)
            starter = max(0.0, s - st)
            rot = max(0.0, 1.0 - s - b)        # the middle band
            rec["pred"] = {"star": round(st, 3), "starter": round(starter, 3),
                           "rotation": round(rot, 3), "bust": round(b, 3),
                           "success": round(s, 3)}  # success kept for sorting/compat
            stamped += 1
    # everyone outside the pool: no probabilities (the model can't see them)
    for p in raw["players"]:
        if p["id"] not in {q["id"] for q in pool}:
            p.pop("pred", None)
    save_json(PLAYERS_FILE, raw)
    print(f"\nStamped outcome probabilities for {stamped} eligible players -> {PLAYERS_FILE.name}")
    top = sorted(pool, key=lambda p: p.get("sm_rank") or 999)[:8]
    for p in top:
        i = pool.index(p)
        st = min(float(pst[i]), float(ps[i]))
        print(f"  #{p.get('sm_rank'):>3} {p['name']:<24} star {st*100:.0f}%  "
              f"starter {(ps[i]-st)*100:.0f}%  rotation {max(0, 1-ps[i]-pb[i])*100:.0f}%  "
              f"bust {pb[i]*100:.0f}%")


if __name__ == "__main__":
    main()
