#!/usr/bin/env python3
"""
analytics.strengths_model — the strengths-based ranking, hardened.

Three layers of robustness on top of the original single ridge fit:

  1. FEATURE SELECTION BY HELD-OUT MERIT — candidate feature sets (strengths
     only; + archetype fits; + age-interaction terms) and ridge lambdas are
     compared on leave-one-year-out CV; the winner is whatever predicts
     UNSEEN draft classes best. (Selection uses the same 4 folds it reports,
     so the headline number is mildly optimistic — noted, not hidden.)
  2. BOOTSTRAP ENSEMBLE — the shipped model is the average of B=300 ridge
     fits on resampled training sets. No handful of players can swing the
     board; averaging linear models = averaging coefficients, so the app
     still gets one simple coefficient vector.
  3. UNCERTAINTY BANDS — each current-class player's rank is computed under
     every bootstrap model; the 5th-95th percentile rank range ships with
     the rank. The board can say "#3 (2-6)" instead of pretending precision.

Features: 10 class-relative strengths, age (class-year ordinal), height,
optionally the 16 archetype fits and age x skill interactions. Age/height
adjusters are LEARNED, printed openly.

Training population: the ELIGIBLE 2020-23 classes (drafted + undrafted who
left college; returners excluded), target = position-relative NBA value.

Usage:
    python -m analytics.strengths_model            # select + validate + show
    python -m analytics.strengths_model --save     # ...and persist for the app
"""

import json
import sys

import numpy as np

from analytics.backtest import MATURE_YEARS, attach_value_target, load_matched, spearman
from core.ages import age_for, class_age_fallback
from core.config import DATASETS_DIR
from core.numeric import height_inches
from model.archetypes import draft_score
from model.strengths import ALL_RECIPES, STRENGTH_KEYS, compute_fits, compute_strengths

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

AGE_ORD = {"Freshman": 0, "Sophomore": 1, "Junior": 2, "Senior": 3,
           "Graduate": 4, "5th Year": 4}
FIT_KEYS = list(ALL_RECIPES)
INTERACTIONS = ["shooting", "scoring", "playmaking", "rim_protection"]

BASE = list(STRENGTH_KEYS) + ["age_ord", "height_in"]
INTER = [f"age_x_{k}" for k in INTERACTIONS]
FEATURE_SETS = {
    "strengths":        BASE,
    "strengths+fits":   BASE + [f"fit:{k}" for k in FIT_KEYS],
    "strengths+inter":  BASE + INTER,
    "full":             BASE + [f"fit:{k}" for k in FIT_KEYS] + INTER,
    # Age-impactor fixes (the Lendeborg problem): a blanket age penalty
    # punishes market-validated seniors, but 1st-round-caliber seniors hit
    # at 50% — as well as 1st-round freshmen. Two remedies tested:
    #   peak   — age x (mean of top-3 strengths): elite-skill seniors escape
    #   market — draft slot at training / mock rank at inference: a senior
    #            the market screens into round 1 inherits that group's
    #            survival curve, not the undrafted-senior average
    # NOTE: age_x_market was tried and REMOVED — held-out identical (+0.815
    # vs +0.818) but the interaction (fit on 12 first-round seniors) pushed
    # validated seniors ABOVE equal-mock freshmen, which the data doesn't
    # support (their hit rates are equal, not better) — it put Lendeborg #1.
    "inter+peak":       BASE + INTER + ["age_x_peak"],
    "inter+market":     BASE + INTER + ["market"],
    # TRUE AGE (Tankathon draft-day age, data.scrape_ages): a 19.9-year-old
    # freshman and an 18.4-year-old freshman were identical under age_ord.
    # agey_x_* interactions use (age_years - 19) so freshmen sit near zero,
    # matching the ordinal semantics. Unscraped players (undrafted rows,
    # deep stubs) impute from their class-year mean — stamped as _age_years.
    "inter+market+agey": list(STRENGTH_KEYS) + ["age_years", "height_in"]
                         + [f"agey_x_{k}" for k in INTERACTIONS] + ["market"],
    # STRENGTH OF SCHEDULE: conference tier (2 high-major / 1 strong-mid /
    # 0 other) — 20 ppg in the SoCon is not 20 ppg in the SEC.
    "inter+market+conf": BASE + INTER + ["market", "conf_tier"],
    "inter+market+agey+conf": list(STRENGTH_KEYS) + ["age_years", "height_in"]
                              + [f"agey_x_{k}" for k in INTERACTIONS]
                              + ["market", "conf_tier"],
    # additive: ordinal age machinery intact, true age as one extra column —
    # lets the model separate old vs young freshmen without losing the
    # class-year survival signal
    "conf+ageadd":      BASE + INTER + ["market", "conf_tier", "age_years"],
}
CONF_TIERS = {  # judgment constants, same spirit as intl LEAGUE_TIERS
    "SEC": 2, "ACC": 2, "Big Ten": 2, "Big 12": 2, "Big East": 2, "Pac-12": 2,
    "WCC": 1, "AAC": 1, "MWC": 1, "A-10": 1,
}
LAMBDAS = (20.0, 60.0, 150.0)
B_BOOT = 300
SEED = 7  # fixed: reproducible boards


def featurize(p: dict, features) -> list[float]:
    s = p.get("strengths") or {}
    fits = p.get("fits") or {}
    age = AGE_ORD.get(p.get("year", ""), 2)
    combine = p.get("combine") or {}
    ht = combine.get("height_w_shoes_in") or height_inches(p.get("height", ""))
    # Market validation: actual draft slot for training rows (stamped as
    # _market_rank), consensus mock rank at inference. 60 -> 1 scale; 0 = off
    # the market's board entirely.
    mrank = p.get("_market_rank") or p.get("_mock_rank")
    market = max(0.0, 61.0 - mrank) if mrank else 0.0
    peak = None
    vals = sorted((v for v in s.values() if v is not None), reverse=True)
    if vals:
        peak = sum(vals[:3]) / min(3, len(vals))

    ay = p.get("_age_years")

    row = []
    for f in features:
        if f == "age_ord":
            row.append(age)
        elif f == "age_years":
            row.append(ay if ay is not None else np.nan)
        elif f == "conf_tier":
            row.append(CONF_TIERS.get(p.get("conference") or "", 0))
        elif f.startswith("agey_x_"):
            v = s.get(f[7:])
            row.append((ay - 19.0) * v if (ay is not None and v is not None)
                       else np.nan)
        elif f == "height_in":
            row.append(ht if ht else np.nan)
        elif f == "market":
            row.append(market)
        elif f == "age_x_market":
            row.append(age * market)
        elif f == "age_x_peak":
            row.append(age * peak if peak is not None else np.nan)
        elif f.startswith("fit:"):
            row.append(fits.get(f[4:], np.nan))
        elif f.startswith("age_x_"):
            v = s.get(f[6:])
            row.append(age * v if v is not None else np.nan)
        else:
            row.append(s.get(f) if s.get(f) is not None else np.nan)
    return row


def _design(records, features):
    return np.array([featurize(r, features) for r in records], float)


def _fit_ridge(X, y, lam):
    med = np.nanmedian(X, axis=0)
    idx = np.where(np.isnan(X))
    X = X.copy(); X[idx] = np.take(med, idx[1])
    mu, sd = X.mean(0), X.std(0) + 1e-9
    Xs = (X - mu) / sd
    coef = np.linalg.solve(Xs.T @ Xs + lam * np.eye(Xs.shape[1]),
                           Xs.T @ (y - y.mean()))
    return {"coef": coef, "mu": mu, "sd": sd, "med": med, "y0": float(y.mean())}


def _predict(m, X):
    X = X.copy()
    idx = np.where(np.isnan(X))
    X[idx] = np.take(np.asarray(m["med"]), idx[1])
    return (X - np.asarray(m["mu"])) / np.asarray(m["sd"]) @ np.asarray(m["coef"]) + m["y0"]


def _loyo(X, y, years, lam):
    rhos = []
    for hold in MATURE_YEARS:
        tr, te = years != hold, years == hold
        if te.sum() < 5:
            continue
        m = _fit_ridge(X[tr], y[tr], lam)
        rhos.append(spearman(list(_predict(m, X[te])), list(y[te])))
    return float(np.mean(rhos)), rhos


def _bagged_fit(X, y, lam, b=B_BOOT, seed=SEED):
    """Bootstrap ensemble. Returns (mean-coef model, list of B models)."""
    rng = np.random.default_rng(seed)
    n = len(y)
    models = []
    for _ in range(b):
        idx = rng.integers(0, n, n)
        models.append(_fit_ridge(X[idx], y[idx], lam))
    mean = {
        "coef": np.mean([m["coef"] for m in models], axis=0),
        "mu": np.mean([m["mu"] for m in models], axis=0),
        "sd": np.mean([m["sd"] for m in models], axis=0),
        "med": np.nanmedian(X, axis=0),
        "y0": float(np.mean([m["y0"] for m in models])),
    }
    return mean, models


def build_training():
    rows = load_matched(years=(2020, 2021, 2022, 2023, 2024, 2025), include_undrafted=True)  # young classes join training (held-out unchanged)
    attach_value_target(rows)
    rows = [r for r in rows if r.get("target") is not None]
    for yr in sorted({r["year"] for r in rows}):
        recs = [r["college_record"] for r in rows if r["year"] == yr]
        compute_strengths(recs, reference=recs)
        compute_fits(recs, reference=recs)
    n_age = 0
    for r in rows:  # market validation at training time = actual draft slot
        r["college_record"]["_market_rank"] = r["pick"]
        a = age_for(r["player"], r["year"], r.get("college", ""))
        if a is not None:
            n_age += 1
        else:  # unscraped (mostly undrafted) -> class-year mean
            a = class_age_fallback(r["college_record"].get("year", ""))
        r["college_record"]["_age_years"] = a
    print(f"True draft-day ages: {n_age}/{len(rows)} scraped, rest imputed "
          f"from class-year means")
    recs = [r["college_record"] for r in rows]
    y = np.array([r["target"] for r in rows], float)
    years = np.array([r["year"] for r in rows])
    n_ud = sum(1 for r in rows if r["pick"] is None)
    print(f"Training population: {len(rows)} eligible players "
          f"({len(rows) - n_ud} drafted + {n_ud} undrafted), classes {sorted(set(int(v) for v in years))}")
    return recs, y, years


def select_and_validate(recs, y, years):
    print("\nLeave-one-year-out mean Spearman by config (selection is on these "
          "same folds — mildly optimistic):")
    best = None
    for name, feats in FEATURE_SETS.items():
        X = _design(recs, feats)
        for lam in LAMBDAS:
            mean_rho, per = _loyo(X, y, years, lam)
            marker = ""
            if best is None or mean_rho > best[0]:
                best = (mean_rho, name, lam, per)
                marker = "  <- best so far"
            print(f"  {name:<16} lam={lam:>5.0f}  {mean_rho:+.3f}{marker}")
    mean_rho, name, lam, per = best
    ds_rho = float(np.mean([
        spearman([draft_score(r) for r, t in zip(recs, years == hold) if t],
                 list(y[years == hold]))
        for hold in MATURE_YEARS if (years == hold).sum() >= 5
    ]))
    print(f"\nSelected: {name} (lambda {lam:.0f}) — held-out {mean_rho:+.3f} "
          f"per-year {[round(r, 3) for r in per]}")
    print(f"Baseline draft_score on the same rows: {ds_rho:+.3f}")
    return name, lam, mean_rho, ds_rho


def main():
    recs, y, years = build_training()
    name, lam, rho_model, rho_score = select_and_validate(recs, y, years)
    feats = FEATURE_SETS[name]
    X = _design(recs, feats)
    mean_model, models = _bagged_fit(X, y, lam)

    print(f"\nTop learned coefficients (bootstrap-averaged, {B_BOOT} fits):")
    order = np.argsort(-np.abs(mean_model["coef"]))[:12]
    for i in order:
        spread = np.std([m["coef"][i] for m in models])
        print(f"    {feats[i]:<22} {mean_model['coef'][i]:>+8.4f}  (±{spread:.4f})")

    # Current class: rank under every bootstrap model -> bands
    from web import store
    pool, _, _ = store.board_filter(store.PLAYERS, store.CURRENT_SEASON_YEAR,
                                    with_stubs=False)
    pool = sorted(pool, key=lambda p: p["rank"])
    Xc = _design(pool, feats)
    pred = _predict(mean_model, Xc)
    rank_mat = np.zeros((len(models), len(pool)), int)
    for bi, m in enumerate(models):
        order_b = np.argsort(-_predict(m, Xc))
        ranks = np.empty(len(pool), int)
        ranks[order_b] = np.arange(1, len(pool) + 1)
        rank_mat[bi] = ranks
    lo = np.percentile(rank_mat, 5, axis=0).astype(int)
    hi = np.percentile(rank_mat, 95, axis=0).astype(int)

    ranked = sorted(zip(pool, pred, lo, hi), key=lambda t: -t[1])
    print(f"\n2026 class — bagged strengths model (rank with 90% band):")
    for i, (p, v, l, h) in enumerate(ranked[:20], 1):
        print(f"  {i:>3} ({l:>2}-{h:<2}) {p['name']:<24} {p['pos']} {p.get('year', '?'):<10} "
              f"model {v * 100:.0f}  mock #{p.get('_mock_rank', '—')}")

    print(f"\nVerdict: bagged '{name}' ships at held-out {rho_model:+.3f} "
          f"(draft_score baseline {rho_score:+.3f}).")

    if "--save" in sys.argv:
        bands = {str(p["id"]): [int(l), int(h)]
                 for p, _, l, h in ranked}
        out = DATASETS_DIR / "strengths_model.json"
        out.write_text(json.dumps({
            "config": name, "lambda": lam, "bootstraps": B_BOOT,
            "features": feats,
            "coef": [float(c) for c in mean_model["coef"]],
            "mu": [float(v) for v in mean_model["mu"]],
            "sd": [float(v) for v in mean_model["sd"]],
            "med": [float(v) for v in mean_model["med"]],
            "y0": mean_model["y0"],
            "rank_bands": bands,
            "validation": {"loyo_spearman_model": rho_model,
                           "loyo_spearman_draft_score": rho_score},
        }, indent=2), encoding="utf-8")
        print(f"Saved -> {out.name}")


if __name__ == "__main__":
    main()
