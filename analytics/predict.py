#!/usr/bin/env python3
"""
analytics.predict — Boom/Bust probabilities, calibrated on the STRENGTHS
MODEL (the actual ranking), not the retired formula.

Boom = P(NBA starter or better), Bust = P(bench or out of the league),
learned from the eligible 2020-23 classes. Each is a 1-D logistic
calibration of the strengths-model score; in leave-one-year-out CV the
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
BUST_MAX_TIER = 1      # bench or never made it
FEATS = FEATURE_SETS["inter+market"]
LAMBDA_RIDGE = 20.0
LAMBDA_LOGIT = 1.0


def _sigmoid(z):
    return 1.0 / (1.0 + np.exp(-np.clip(z, -30, 30)))


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
    return ys, yb


def loyo_cv(rows):
    """Held-out AUC per year; the strengths model is refit per fold."""
    rows = [r for r in rows if r.get("target") is not None] or rows
    attach_value_target(rows)
    rows = [r for r in rows if r.get("target") is not None]
    _prep(rows)
    recs = [r["college_record"] for r in rows]
    X = _design(recs, FEATS)
    yv = np.array([r["target"] for r in rows], float)
    ys, yb = _labels(rows)
    years = np.array([r["year"] for r in rows])
    out = {}
    for hold in MATURE_YEARS:
        tr, te = years != hold, years == hold
        if te.sum() < 5:
            continue
        m = _fit_ridge(X[tr], yv[tr], LAMBDA_RIDGE)
        s_tr, s_te = _sm_predict(m, X[tr]), _sm_predict(m, X[te])
        cs = fit_logistic_1d(s_tr, ys[tr])
        cb = fit_logistic_1d(-s_tr, yb[tr])
        out[hold] = {
            "auc_success": auc(ys[te], calib_prob(cs, s_te)),
            "auc_bust": auc(yb[te], calib_prob(cb, -s_te)),
            "n": int(te.sum()),
        }
    return out


class Head:
    """Calibrated head: strengths-model score -> probability."""

    def __init__(self, ridge, calib, flip=False):
        self.ridge, self.calib, self.flip = ridge, calib, flip

    def prob(self, records):
        s = _sm_predict(self.ridge, _design(records, FEATS))
        return calib_prob(self.calib, -s if self.flip else s)


def train_final(rows):
    rows = [r for r in rows if r.get("target") is not None] or rows
    attach_value_target(rows)
    rows = [r for r in rows if r.get("target") is not None]
    _prep(rows)
    recs = [r["college_record"] for r in rows]
    X = _design(recs, FEATS)
    yv = np.array([r["target"] for r in rows], float)
    ys, yb = _labels(rows)
    m = _fit_ridge(X, yv, LAMBDA_RIDGE)
    s = _sm_predict(m, X)
    return (Head(m, fit_logistic_1d(s, ys)),
            Head(m, fit_logistic_1d(-s, yb), flip=True))


def main():
    dry = "--dry-run" in sys.argv
    rows = load_matched(include_undrafted=True)
    attach_value_target(rows)
    rows = [r for r in rows if r.get("target") is not None]
    ys, yb = _labels(rows)
    print(f"Training pool: {len(rows)} eligible players "
          f"(success {int(ys.sum())}, bust {int(yb.sum())})")

    cv = loyo_cv(rows)
    print("\nLeave-one-year-out held-out AUC (strengths-model calibration):")
    for y, m in cv.items():
        print(f"  {y}: success {m['auc_success']:.3f}  bust {m['auc_bust']:.3f}  (n={m['n']})")
    print(f"  MEAN: success {np.mean([m['auc_success'] for m in cv.values()]):.3f}  "
          f"bust {np.mean([m['auc_bust'] for m in cv.values()]):.3f}")
    if dry:
        return

    # Stamp the current class pool (only pool players have model features)
    head_s, head_b = train_final(rows)
    from web import store  # pool already has strengths + mock stamped
    pool, _, _ = store.board_filter(store.PLAYERS, store.CURRENT_SEASON_YEAR,
                                    with_stubs=False)
    ps, pb = head_s.prob(pool), head_b.prob(pool)
    raw = load_json(PLAYERS_FILE)
    by_id = {p["id"]: p for p in raw["players"]}
    stamped = 0
    for p, s, b in zip(pool, ps, pb):
        rec = by_id.get(p["id"])
        if rec is not None:
            rec["pred"] = {"success": round(float(s), 3), "bust": round(float(b), 3)}
            stamped += 1
    # everyone outside the pool: no probabilities (the model can't see them)
    for p in raw["players"]:
        if p["id"] not in {q["id"] for q in pool}:
            p.pop("pred", None)
    save_json(PLAYERS_FILE, raw)
    print(f"\nStamped Boom/Bust for {stamped} eligible players -> {PLAYERS_FILE.name}")
    top = sorted(pool, key=lambda p: p.get("sm_rank") or 999)[:8]
    for p, s, b in [(p, ps[pool.index(p)], pb[pool.index(p)]) for p in top]:
        print(f"  #{p.get('sm_rank'):>3} {p['name']:<24} boom {s*100:.0f}%  bust {b*100:.0f}%")


if __name__ == "__main__":
    main()
