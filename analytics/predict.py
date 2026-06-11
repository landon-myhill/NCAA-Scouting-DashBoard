#!/usr/bin/env python3
"""
analytics.predict — ML success/bust probabilities for every prospect.
---------------------------------------------------------------------
The draft-score formula RANKS prospects. This module answers a different
question: "how LIKELY is this profile to succeed (starter/star) or bust
(bench/out of the league)?" — learned from what actually happened to the
2020-2023 drafted classes (mature NBA careers only).

Two L2-regularized logistic heads (numpy Newton solver), chosen by held-out
leave-one-year-out CV — the same honesty guard as tune.py:

  SUCCESS — 1-D logistic calibration of draft_score itself (held-out AUC
            0.68 vs the box-score outcome tiers). A multi-feature logistic
            on the components scored WORSE: the formula's multiplicative
            conference/age structure beats additive log-odds at ranking
            upside, so we calibrate it into a probability instead of
            re-learning it badly.

  BUST    — also score-calibrated (held-out AUC 0.61). Under the old
            impact-stat tiers a multi-feature head added signal (0.73); under
            the box-score production tiers it no longer does (0.58 vs 0.61),
            so it was removed — same shipping rule as everything else.

Selection-bias caveat (see tune.py / README): we only observe NBA outcomes
for DRAFTED players, who are overwhelmingly power-conference. Probabilities
are therefore calibrated as "IF this player is a drafted-caliber prospect".

Outputs (written into players.json per player):
    pred.success   P(NBA starter or better)      0..1
    pred.bust      P(bench-or-worse / no NBA)    0..1

Usage:
    python -m analytics.predict            # validate (LOYO CV) + stamp players.json
    python -m analytics.predict --dry-run  # validate only, don't write
"""

import sys

import numpy as np

from analytics.backtest import MATURE_YEARS, attach_value_target, load_matched
from core import PLAYERS_FILE, load_json, save_json
from model.archetypes import draft_score

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

# Career tiers (backtest.TIER_VALUE): no_nba=0 bench=1 rotation=2 starter=3 star=4
SUCCESS_MIN_TIER = 3   # starter or star
BUST_MAX_TIER = 1      # bench or never made it

LAMBDA_SUCCESS = 1.0   # 1-D calibrations barely need shrinkage
LAMBDA_BUST = 1.0


# ── Features ─────────────────────────────────────────────────────────────────

def featurize_success(player: dict) -> list[float]:
    """Both heads calibrate the formula itself: one feature."""
    return [draft_score(player)]


featurize_bust = featurize_success


def _impute_standardize(X, mu=None, med=None, sd=None):
    """Median-impute NaNs, then z-score. Returns (Xs, mu, med, sd)."""
    if med is None:
        med = np.nanmedian(X, axis=0)
    idx = np.where(np.isnan(X))
    X = X.copy()
    X[idx] = np.take(med, idx[1])
    if mu is None:
        mu, sd = X.mean(0), X.std(0) + 1e-9
    return (X - mu) / sd, mu, med, sd


# ── L2 logistic regression (Newton) ──────────────────────────────────────────

def _sigmoid(z):
    return 1.0 / (1.0 + np.exp(-np.clip(z, -30, 30)))


def fit_logistic(Xs, y, lam, iters=25):
    """Return coefficient vector (intercept first, unpenalized)."""
    n, p = Xs.shape
    A = np.hstack([np.ones((n, 1)), Xs])
    b = np.zeros(p + 1)
    reg = lam * np.eye(p + 1)
    reg[0, 0] = 0.0  # don't shrink the intercept
    for _ in range(iters):
        prob = _sigmoid(A @ b)
        W = np.clip(prob * (1 - prob), 1e-6, None)
        H = A.T @ (A * W[:, None]) + reg
        g = A.T @ (y - prob) - reg @ b
        step = np.linalg.solve(H, g)
        b += step
        if np.max(np.abs(step)) < 1e-8:
            break
    return b


def predict_prob(b, Xs):
    return _sigmoid(np.hstack([np.ones((Xs.shape[0], 1)), Xs]) @ b)


def auc(y_true, scores) -> float:
    """Rank-based AUC (probability a random positive outranks a random negative)."""
    pos = [s for s, t in zip(scores, y_true) if t == 1]
    neg = [s for s, t in zip(scores, y_true) if t == 0]
    if not pos or not neg:
        return float("nan")
    wins = sum((p > n) + 0.5 * (p == n) for p in pos for n in neg)
    return wins / (len(pos) * len(neg))


# ── A trained head: features -> probability ──────────────────────────────────

class Head:
    """One logistic head with its featurizer + imputation/scaling state."""

    def __init__(self, featurize, lam):
        self.featurize = featurize
        self.lam = lam
        self.b = self.mu = self.med = self.sd = None

    def matrix(self, records):
        return np.array([self.featurize(r) for r in records], dtype=float)

    def fit(self, records, y):
        X = self.matrix(records)
        Xs, self.mu, self.med, self.sd = _impute_standardize(X)
        self.b = fit_logistic(Xs, y, self.lam)
        return self

    def prob(self, records):
        X = self.matrix(records)
        Xs, *_ = _impute_standardize(X, self.mu, self.med, self.sd)
        return predict_prob(self.b, Xs)


def make_heads():
    return (Head(featurize_success, LAMBDA_SUCCESS),
            Head(featurize_bust, LAMBDA_BUST))


# ── Train / validate ─────────────────────────────────────────────────────────

def _labels(rows):
    y_success = np.array([1.0 if r["tier_val"] >= SUCCESS_MIN_TIER else 0.0 for r in rows])
    y_bust = np.array([1.0 if r["tier_val"] <= BUST_MAX_TIER else 0.0 for r in rows])
    return y_success, y_bust


def loyo_cv(rows):
    """Leave-one-year-out CV: held-out AUC for both heads, per year."""
    recs = [r["college_record"] for r in rows]
    y_success, y_bust = _labels(rows)
    years = np.array([r["year"] for r in rows])
    out = {}
    for hold in MATURE_YEARS:
        tr, te = years != hold, years == hold
        if te.sum() < 5:
            continue
        head_s, head_b = make_heads()
        tr_recs = [r for r, m in zip(recs, tr) if m]
        te_recs = [r for r, m in zip(recs, te) if m]
        head_s.fit(tr_recs, y_success[tr])
        head_b.fit(tr_recs, y_bust[tr])
        out[hold] = {
            "auc_success": auc(y_success[te], head_s.prob(te_recs)),
            "auc_bust": auc(y_bust[te], head_b.prob(te_recs)),
            "n": int(te.sum()),
        }
    return out


def train_final(rows):
    """Fit both heads on all mature years."""
    recs = [r["college_record"] for r in rows]
    y_success, y_bust = _labels(rows)
    head_s, head_b = make_heads()
    return head_s.fit(recs, y_success), head_b.fit(recs, y_bust)


# ── Main ─────────────────────────────────────────────────────────────────────

def main():
    dry = "--dry-run" in sys.argv

    rows = load_matched()
    attach_value_target(rows)
    if len(rows) < 100:
        print(f"ERROR: only {len(rows)} matched training rows — is datasets/history populated?")
        sys.exit(1)
    y_success, y_bust = _labels(rows)
    print(f"Training pool: {len(rows)} drafted players, classes {MATURE_YEARS}")
    print(f"  success (starter+): {int(y_success.sum())}   bust (bench/none): {int(y_bust.sum())}")

    # Honesty guard: held-out performance per year
    cv = loyo_cv(rows)
    print("\nLeave-one-year-out held-out AUC:")
    print(f"  {'year':>6}  {'success':>8}  {'bust':>6}  {'n':>4}")
    for y, m in cv.items():
        print(f"  {y:>6}  {m['auc_success']:>8.3f}  {m['auc_bust']:>6.3f}  {m['n']:>4}")
    mean_s = np.mean([m["auc_success"] for m in cv.values()])
    mean_b = np.mean([m["auc_bust"] for m in cv.values()])
    print(f"  {'MEAN':>6}  {mean_s:>8.3f}  {mean_b:>6.3f}")

    if dry:
        print("\n--dry-run: not writing players.json")
        return

    # Final fit on everything, then stamp the current board
    head_s, head_b = train_final(rows)
    raw = load_json(PLAYERS_FILE)
    players = raw["players"]
    ps, pb = head_s.prob(players), head_b.prob(players)
    for p, s, b in zip(players, ps, pb):
        p["pred"] = {"success": round(float(s), 3), "bust": round(float(b), 3)}
    save_json(PLAYERS_FILE, raw)
    print(f"\nStamped pred.success / pred.bust onto {len(players)} players -> {PLAYERS_FILE.name}")

    top = sorted(players, key=lambda p: p["rank"])[:10]
    print("\nTop 10 by board rank:")
    for p in top:
        print(f"  #{p['rank']:>3} {p['name']:<26} success {p['pred']['success']*100:4.0f}%"
              f"   bust {p['pred']['bust']*100:4.0f}%")


if __name__ == "__main__":
    main()
