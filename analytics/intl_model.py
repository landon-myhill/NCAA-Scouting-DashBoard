#!/usr/bin/env python3
"""
analytics.intl_model — EXPERIMENTAL ranking for international / G-League
prospects, so Wemby-types appear in the board instead of "—".

Honesty first: the training set is tiny (~40 historical internationals with
pre-draft stats + NBA outcomes), so this is deliberately simple — league
tier x per-36 production x age x market — ridge-fit to the SAME position-
relative NBA-value target the main model uses, so its output lives on the
same 0-100 scale and slots straight into the board. Bands are extra wide.

League tiers are a documented judgment call (EuroLeague pro minutes mean
more than ABA junior-circuit minutes); everything else is learned.

Usage:
    python -m analytics.intl_model            # validate + historical sanity
    python -m analytics.intl_model --save     # persist for the app
"""

import json
import sys
from datetime import date

import numpy as np

from analytics.backtest import spearman
from core import HISTORY_DIR, load_json
from core.config import DATASETS_DIR, INTL_DIR
from core.names import normalize_name

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

MATURE = (2020, 2021, 2022, 2023)

# League strength tiers (judgment, documented). Unknown leagues get 0.6.
LEAGUE_TIERS = {
    "EuroLeague": 1.0, "Liga ACB": 0.95, "BSL": 0.85, "EuroCup": 0.85,
    "NBL": 0.85, "LNB Pro A": 0.85, "LNB Élite": 0.85, "LNB Elite": 0.85,
    "ABA": 0.70, "LBA": 0.85, "OTE": 0.50,
}
TEAM_TIERS = {  # rows where bbref left the league blank
    "GLI": 0.85,            # G-League Ignite (vs pros)
    "City Reapers": 0.50,   # Overtime Elite
}
FEATURES = ["pts36_adj", "reb36_adj", "ast36_adj", "age", "market"]
LAMBDA = 40.0
B_BOOT = 300


def _tier(rec):
    return LEAGUE_TIERS.get(rec.get("league") or "",
                            TEAM_TIERS.get(rec.get("team") or "", 0.6))


def featurize(rec: dict, mock_rank=None) -> list[float]:
    s = rec.get("stats") or {}
    mpg = s.get("MPG") or 0
    scale = 36.0 / max(mpg, 15.0) if mpg else 1.0
    tier = _tier(rec)
    age = None
    if rec.get("born"):
        try:
            b = date.fromisoformat(rec["born"])
            age = rec["_draft_year"] + 0.5 - (b.year + b.month / 12.0)
        except Exception:
            age = None
    if age is None and rec.get("age_label"):
        try:
            age = float(rec["age_label"].split()[-1])
        except Exception:
            age = None
    market = max(0.0, 61.0 - mock_rank) if mock_rank else 0.0
    return [
        (s.get("PPG") or 0) * scale * tier,
        (s.get("RPG") or 0) * scale * tier,
        (s.get("APG") or 0) * scale * tier,
        age if age is not None else np.nan,
        market,
    ]


def build_training():
    rows = []
    for y in MATURE:
        f = INTL_DIR / f"intl_{y}.json"
        if not f.exists():
            continue
        intl = {r.get("norm_name") or normalize_name(r["name"]): r
                for r in load_json(f).get("players", [])}
        manual = INTL_DIR / "intl_manual.json"
        if manual.exists():
            for r in json.loads(manual.read_text(encoding="utf-8")).get(str(y), []):
                intl[r.get("norm_name") or normalize_name(r["name"])] = r
        for pick in load_json(HISTORY_DIR / f"draft_results_{y}.json")["picks"]:
            rec = intl.get(normalize_name(pick["player"]))
            if rec is None or pick.get("nba_value") is None:
                continue
            rec = dict(rec)
            rec["_draft_year"] = y
            rows.append({"year": y, "name": pick["player"], "rec": rec,
                         "pick": pick["pick_overall"],
                         "value": pick["nba_value"]})
    return rows


def _fit(X, y, lam=LAMBDA):
    med = np.nanmedian(X, axis=0)
    idx = np.where(np.isnan(X))
    X = X.copy(); X[idx] = np.take(med, idx[1])
    mu, sd = X.mean(0), X.std(0) + 1e-9
    coef = np.linalg.solve(((X - mu) / sd).T @ ((X - mu) / sd) + lam * np.eye(X.shape[1]),
                           ((X - mu) / sd).T @ (y - y.mean()))
    return {"coef": coef, "mu": mu, "sd": sd, "med": med, "y0": float(y.mean())}


def _predict(m, X):
    X = X.copy()
    idx = np.where(np.isnan(X))
    X[idx] = np.take(np.asarray(m["med"]), idx[1])
    return (X - np.asarray(m["mu"])) / np.asarray(m["sd"]) @ np.asarray(m["coef"]) + m["y0"]


def main():
    rows = build_training()
    X = np.array([featurize(r["rec"], r["pick"]) for r in rows], float)
    y = np.array([r["value"] for r in rows], float)
    years = np.array([r["year"] for r in rows])
    print(f"Training set: {len(rows)} historical internationals with stats + outcomes")

    # Leave-one-year-out — tiny folds, so read this as indicative, not precise
    held = []
    for hold in MATURE:
        tr, te = years != hold, years == hold
        if te.sum() < 3:
            continue
        m = _fit(X[tr], y[tr])
        rho = spearman(list(_predict(m, X[te])), list(y[te]))
        held.append(rho)
        print(f"  held-out {hold}: rho {rho:+.3f} (n={int(te.sum())})")
    print(f"  mean: {np.mean(held):+.3f}")

    # Point estimate = the full-data fit (averaging bootstrap PARAMETERS
    # flattens the model at n=41); bootstraps are kept for spread only.
    final = _fit(X, y)
    rng = np.random.default_rng(7)
    models = [_fit(X[rng.integers(0, len(y), len(y))], y) for _ in range(B_BOOT)]
    spread = float(np.mean(np.std([_predict(m, X) for m in models], axis=0)))
    print(f"\nbootstrap prediction spread (1sd): ±{spread*100:.0f} grade points")

    pred = _predict(final, X)
    print("\nHistorical sanity (intl grade 0-100 vs what actually happened):")
    for r, p in sorted(zip(rows, pred), key=lambda t: -t[1])[:12]:
        print(f"  {r['name']:<24} {r['year']} pick #{r['pick']:<3} grade {p*100:.0f}  "
              f"actual value {r['value']:.2f}")

    rho_all = spearman(list(pred), list(y))
    print(f"\nIn-sample Spearman {rho_all:+.3f} | held-out mean {np.mean(held):+.3f}")

    if "--save" in sys.argv:
        out = DATASETS_DIR / "intl_model.json"
        out.write_text(json.dumps({
            "features": FEATURES,
            "coef": [float(c) for c in final["coef"]],
            "mu": [float(v) for v in final["mu"]],
            "sd": [float(v) for v in final["sd"]],
            "med": [float(v) for v in final["med"]],
            "y0": final["y0"],
            "league_tiers": LEAGUE_TIERS, "team_tiers": TEAM_TIERS,
            "spread_sd": spread,
            "validation": {"loyo_mean": float(np.mean(held)), "n": len(rows)},
        }, indent=2, ensure_ascii=False), encoding="utf-8")
        print(f"Saved -> {out.name}")


if __name__ == "__main__":
    main()
