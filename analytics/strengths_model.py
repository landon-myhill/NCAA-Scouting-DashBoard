#!/usr/bin/env python3
"""
analytics.strengths_model — candidate ranking built from the measured
strengths, with explicit AGE and HEIGHT adjusters.

Per the project owner's design:
  - features = the 10 class-relative strength percentiles (model/strengths.py)
    plus an age factor (class-year ordinal) and absolute height — the
    "age +/-" and "height +/-" are LEARNED coefficients, printed openly,
    not hand-asserted.
  - training population = the ELIGIBLE classes (drafted + undrafted who left
    college; returners excluded) with position-relative NBA value as target.
  - honesty guard = leave-one-year-out CV against the current draft_score on
    the SAME rows. Ship only on held-out merit (or as an ensemble member).

Usage:
    python -m analytics.strengths_model            # validate + show 2026 board
"""

import sys

import numpy as np

from analytics.backtest import MATURE_YEARS, attach_value_target, load_matched, spearman
from core.numeric import height_inches
from model.archetypes import draft_score
from model.strengths import STRENGTH_KEYS, compute_strengths

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

AGE_ORD = {"Freshman": 0, "Sophomore": 1, "Junior": 2, "Senior": 3,
           "Graduate": 4, "5th Year": 4}
FEATURES = list(STRENGTH_KEYS) + ["age_ord", "height_in"]
LAMBDA = 60.0


def _stamp_class_strengths(rows) -> None:
    """Class-relative strengths for each training class's ELIGIBLE pool."""
    for y in sorted({r["year"] for r in rows}):
        recs = [r["college_record"] for r in rows if r["year"] == y]
        compute_strengths(recs, reference=recs)


def featurize(p: dict) -> list[float]:
    s = p.get("strengths") or {}
    row = [s.get(k) if s.get(k) is not None else np.nan for k in STRENGTH_KEYS]
    row.append(AGE_ORD.get(p.get("year", ""), 2))
    combine = p.get("combine") or {}
    ht = combine.get("height_w_shoes_in") or height_inches(p.get("height", ""))
    row.append(ht if ht else np.nan)
    return row


def _design(records):
    X = np.array([featurize(r) for r in records], float)
    return X


def _fit_ridge(X, y, lam=LAMBDA):
    med = np.nanmedian(X, axis=0)
    idx = np.where(np.isnan(X))
    X = X.copy(); X[idx] = np.take(med, idx[1])
    mu, sd = X.mean(0), X.std(0) + 1e-9
    Xs = (X - mu) / sd
    coef = np.linalg.solve(Xs.T @ Xs + lam * np.eye(Xs.shape[1]),
                           Xs.T @ (y - y.mean()))
    return {"coef": coef, "mu": mu, "sd": sd, "med": med, "y0": float(y.mean())}


def _predict(model, X):
    X = X.copy()
    idx = np.where(np.isnan(X))
    X[idx] = np.take(model["med"], idx[1])
    return (X - model["mu"]) / model["sd"] @ model["coef"] + model["y0"]


def train_validate():
    rows = load_matched(include_undrafted=True)
    attach_value_target(rows)
    rows = [r for r in rows if r.get("target") is not None]
    _stamp_class_strengths(rows)
    recs = [r["college_record"] for r in rows]
    X = _design(recs)
    y = np.array([r["target"] for r in rows], float)
    years = np.array([r["year"] for r in rows])
    n_ud = sum(1 for r in rows if r["pick"] is None)
    print(f"Training population: {len(rows)} eligible players "
          f"({len(rows) - n_ud} drafted + {n_ud} undrafted), classes {sorted(set(years))}")

    print("\nLeave-one-year-out held-out Spearman vs NBA value (same rows):")
    print(f"  {'year':>6}  {'strengths-model':>15}  {'draft_score':>11}")
    sm, ds = [], []
    for hold in MATURE_YEARS:
        tr, te = years != hold, years == hold
        if te.sum() < 5:
            continue
        m = _fit_ridge(X[tr], y[tr])
        pred = _predict(m, X[te])
        rho_m = spearman(list(pred), list(y[te]))
        rho_d = spearman([draft_score(r) for r, t in zip(recs, te) if t],
                         list(y[te]))
        sm.append(rho_m); ds.append(rho_d)
        print(f"  {hold:>6}  {rho_m:>+15.3f}  {rho_d:>+11.3f}")
    print(f"  {'MEAN':>6}  {np.mean(sm):>+15.3f}  {np.mean(ds):>+11.3f}")

    final = _fit_ridge(X, y)
    print("\nLearned adjusters (standardized ridge coefficients):")
    order = np.argsort(-np.abs(final["coef"]))
    for i in order:
        print(f"    {FEATURES[i]:<18} {final['coef'][i]:>+8.4f}")
    return final, (float(np.mean(sm)), float(np.mean(ds)))


def score_current(final):
    """Score the current curated class with the trained model."""
    from web import store  # strengths already stamped at store import
    pool, _, _ = store.board_filter(store.PLAYERS, store.CURRENT_SEASON_YEAR,
                                    with_stubs=False)
    pool = sorted(pool, key=lambda p: p["rank"])
    X = _design(pool)
    pred = _predict(final, X)
    ranked = sorted(zip(pool, pred), key=lambda t: -t[1])
    print(f"\n2026 class under the strengths model (n={len(pool)}):")
    print(f"  {'#':>3} {'player':<24} {'pos':<3} {'age':<10} "
          f"{'model':>6} {'board':>6} {'mock':>5}")
    for i, (p, v) in enumerate(ranked[:25], 1):
        print(f"  {i:>3} {p['name']:<24} {p['pos']:<3} {p.get('year','?'):<10} "
              f"{v:>6.3f} {'#' + str(p['rank']):>6} "
              f"{'#' + str(p.get('_mock_rank', '—')):>5}")
    return ranked


def save_model(final, validation) -> None:
    """Persist for the web app (datasets/strengths_model.json) — the app only
    predicts; training/validation stays here in analytics."""
    import json
    from core.config import DATASETS_DIR
    out = DATASETS_DIR / "strengths_model.json"
    out.write_text(json.dumps({
        "features": FEATURES,
        "coef": [float(c) for c in final["coef"]],
        "mu": [float(v) for v in final["mu"]],
        "sd": [float(v) for v in final["sd"]],
        "med": [float(v) for v in final["med"]],
        "y0": final["y0"],
        "validation": validation,
    }, indent=2), encoding="utf-8")
    print(f"\nSaved model -> {out.name}")


def main():
    final, (rho_model, rho_score) = train_validate()
    score_current(final)
    verdict = ("strengths model WINS held-out — candidate to lead the ranking"
               if rho_model > rho_score + 0.02 else
               "strengths model TIES the formula — ensemble both" if rho_model > rho_score - 0.02
               else "strengths model LOSES held-out — keep as descriptive layer")
    print(f"\nVerdict: {verdict} ({rho_model:+.3f} vs {rho_score:+.3f}).")
    if "--save" in sys.argv:
        save_model(final, {"loyo_spearman_model": rho_model,
                           "loyo_spearman_draft_score": rho_score})


if __name__ == "__main__":
    main()
