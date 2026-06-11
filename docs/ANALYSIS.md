# Predicting NBA Career Outcomes from NCAA Production: Methodology and Findings of the Scouting Dashboard Model

*NCAA Scouting Dashboard project — June 11, 2026*

---

## Abstract

We develop and validate a statistical system for ranking NCAA draft prospects by predicted NBA career value. Using seven draft classes (2020–2026) restricted to genuinely draft-eligible populations (n = 427 training careers), we construct a position-relative, box-score-based outcome metric; derive ten class-relative skill "strengths" per player; and fit a bootstrap-aggregated ridge regression whose features are selected exclusively by leave-one-year-out (LOYO) cross-validation. The shipped model achieves a mean held-out Spearman correlation of **+0.818** with realized NBA value, against **+0.249** for the project's legacy heuristic score and roughly **+0.37** for the NBA's actual draft order. A calibrated probability layer attains held-out AUC of **0.889** (success: starter-or-better) and **0.914** (bust). Secondary studies document: (i) the model's systematic miss profile (low-usage "glue" players); (ii) a conditional "fragility" effect in which shooting-dependent top prospects bust at elevated rates (permutation p = 0.010, n = 48); and (iii) multiple hypotheses that failed validation and were rejected, including true draft-day age, archetype-fit features, and an age × market interaction. We report all of these, including the failures, as a record of what the data does and does not support.

---

## 1. Introduction

The project began with a heuristic draft score (weighted box-score composite with anthropometric bonuses). Its correlation with actual NBA outcomes, measured honestly on held-out draft classes, was +0.249 — better than nothing, far worse than the draft market. The work documented here replaced that heuristic with a validated statistical pipeline under one governing rule:

> **No change ships unless it improves (or at minimum preserves) held-out performance on draft classes the model has never seen, and survives face-validity review of the resulting boards.**

This rule rejected several intuitively appealing features (§9). It is the project's most important methodological artifact.

## 2. Data

### 2.1 Population definition

Each draft class is restricted to its *eligible population*: players who were actually drafted, plus players whose final college season it was and who went undrafted. Players who returned to school are excluded (they were not draft outcomes of that class). Class boards are further restricted to curated ~100-player lists supplied by the project owner.

| Component | Source | n |
|---|---|---|
| College production, 2020–2026 | Season scrapes (per-game + advanced) | ~100/class curated |
| NBA careers (drafted) | Basketball-Reference | 278 |
| NBA careers (undrafted eligibles) | Basketball-Reference | 149 |
| Combine anthro/athletic, 2020–2026 | NBA combine tables | 6 of 7 years + 2023 manual |
| International prospects | Basketball-Reference intl/G-League pages | 41 matched |
| Draft-day ages | Tankathon (per-year draft pages + big board) | 595 |
| Market consensus | Mock-rank order of curated boards; actual draft slot | all classes |

Total training sample: **427 careers** with usable targets across 2020–2025.

### 2.2 Known data limitations

- One season of college box score per player; no play-by-play, tracking, on/off, or schedule-adjusted data.
- Selection bias: only players who entered the draft are observed; development and landing-spot effects are unmodeled.
- 2024–2025 careers span only 1–2 NBA seasons (treated specially, §3.3).

## 3. The Outcome Variable: Position-Relative NBA Value

### 3.1 Rejection of impact composites

VORP/WS/BPM-based grading was rejected on face validity: impact composites are team-context dependent and reward role longevity over production (e.g., a durable backup big accumulating Win Shares graded "starter"; an efficient sixth man graded "star"). The replacement is pure box-score production, graded within position group.

### 3.2 Definition

For each career, compute per-career rates and percentile each **within position group (G/F/C)** across the pooled population:

```
nba_value = .35·pct(PPG) + .25·pct(MPG) + .15·pct(RPG) + .15·pct(APG) + .10·pct(games/season)
```

MPG serves as the coach-revealed role variable. Career tiers are bands on this score — star ≥ .90, starter ≥ .72, rotation ≥ .32, bench < .32, no_nba (< 10 games) — with two **WS/48 quality floors** (star requires WS/48 ≥ .075; starter ≥ .040) so that attaining a role with below-replacement efficiency cannot grade as success.

### 3.3 Young classes

Careers from 2024–2025 cannot be pooled with six-season careers. They are graded **within their own class** (per-class percentiles), yielding honest early tiers (e.g., Flagg = star among 2025 peers) flagged as early-career in the UI. Known warts: small within-class position groups occasionally misgrade (Edey), and the WS/48 floor is harsh on rookie-noisy efficiency (Sarr).

## 4. Feature Construction

### 4.1 Strengths

Ten skill percentiles per player — scoring, shooting, playmaking, finishing, rim pressure, rebounding, rim protection, perimeter defense, ball security, size — computed from per-36 and advanced stats, percentiled **within position group within class** (a 95 means "95th percentile among this class's guards"). A parallel absolute scale (vs the whole class) supports archetype recipes for jobs measured in absolute terms.

**Physical exception (June 2026):** `size` is percentiled against the union of *all* curated classes 2020–2026, not the single class. Physical measurements have no class context, class pools are small, and class composition (a guard-heavy year) was found to distort physical percentiles (the "Flagg 23rd-percentile rebounding" artifact). Production strengths remain class-relative by design: dominance is always measured against actual competition.

### 4.2 Market validation feature

`market = max(0, 61 − rank)`, where rank is the **actual draft slot at training time** and the **consensus mock rank at inference**. This grafts the scouting market's information (athleticism, medicals, intel) onto the statistical model without inheriting its ordering. Empirically the single largest coefficient; see §8.1 for evidence the model still beats the market it borrows from.

### 4.3 Strength of schedule

`conf_tier` ∈ {2: SEC/ACC/Big Ten/Big 12/Big East/Pac-12, 1: WCC/AAC/MWC/A-10, 0: other} — judgment constants in the spirit of the international league tiers. Validated +0.813 → +0.821 held-out, improving **all four** test years; the cleanest single-feature win in the project.

## 5. The Ranking Model

### 5.1 Specification

Ridge regression (closed-form, standardized features, median imputation) of `nba_value` on the selected feature set. The shipped configuration, chosen by LOYO from eight candidates × three λ values:

**`inter+market+conf`** = 10 strengths + class-year ordinal + height (inches) + age × {shooting, scoring, playmaking, rim protection} interactions + market + conf_tier; λ = 60.

### 5.2 Robustness layers

1. **Feature selection by held-out merit only.** Selection uses the same four folds it reports, so headline numbers are mildly optimistic; this is disclosed rather than hidden.
2. **Bootstrap aggregation** (B = 300, fixed seed): the shipped model is the average of 300 resampled fits; no small group of players can swing the board.
3. **Rank uncertainty bands:** every current prospect is ranked under all 300 bootstrap models; the 5th–95th percentile rank range ships with the rank ("#3 (2–6)").

### 5.3 Headline validation

| Model | Held-out Spearman (mean of 2020–23 folds) |
|---|---|
| Legacy draft score | +0.249 |
| NBA draft order (same rows, in-sample) | ~+0.37 |
| Ridge, strengths only | ~+0.74 |
| + age interactions + market | +0.813 |
| + conf_tier (shipped) | **+0.818** (per-year +0.833/+0.807/+0.848/+0.785) |

(The +0.821 measured before the pooled-size change moved to +0.818 after it — two folds improved, two declined; treated as a statistical tie and accepted for the interpretability gain.)

Training on all six classes (adding 2024–25 rows) left held-out performance on settled classes unchanged at +0.813→+0.818 scale — more data at zero cost.

## 6. Probability Calibration (Boom/Bust)

Binary targets: **success** = starter or star; **bust** = bench or never-NBA. The strengths-model score is calibrated to probabilities by a 50/50 blend of (i) binned isotonic regression (quantile bins, min 25/bin, PAVA) and (ii) L2-regularized logistic regression — the blend prevents both the empty-top-bin artifact (raw isotonic) and the flattened-top artifact (binned-only). Ridge and calibration are refit inside each LOYO fold (no leakage).

**Held-out AUC: success 0.889, bust 0.914.** Resulting tails match empirical base rates: consensus-top prospects ~70% success / 1–3% bust; deep-board seniors carry explicit rotation-risk mass rather than fabricated certainty.

## 7. International Prospects

A separate model (n = 41 matched 2020–2023): per-36 production scaled by judgment-constant league tiers (EuroLeague 1.0 … OTE 0.50) plus age and height, ridge-fit and blended 50/50 with a log pick-value curve fit on ~230 drafted players. Point estimates use the full-data fit (bootstrap *parameter* averaging at n = 41 was found to flatten all grades and was abandoned — bootstrap *predictions*, not parameters, at small n). Held-out Spearman ~+0.72. Face validity: Wembanyama grades #2 in the 2023 class; LaMelo Ball backtest grade 81. Known blind spot: teenage stars in strong leagues whose per-36 understates dominance (Şengün, Turkish MVP at 18, grades mid-50s).

## 8. Secondary Studies

### 8.1 Model vs market

Where the market missed, the model frequently did not (held-out ranks): Maxey (model #17, pick #21), **Bane (model #20, pick #30)**, Haliburton (#10 vs #12), Jalen Williams (#10 vs #12). Largest model-over-market steals that hit: Cole Anthony (model #4, pick #15), Bane (+10), Tre Jones (+10), Cam Thomas (+10). Conversely the model shares the market's misses on hyped freshmen (§8.3) — unsurprising given the market feature.

### 8.2 Missed gems (false negatives)

Of 47 eventual stars/starters in 2020–23, only **6** were ranked worse than #25 in-class by the held-out model: Camara, Rollins, Tre Jones, Dosunmu, Herb Jones, Nembhard. Their shared profile: ~83rd percentile playmaking, ~70th percentile perimeter defense, 100% drafted, low ball-security percentile, latent FT% shooting signal. A constructed "glue" feature did not improve held-out performance (the linear model partially captures it); the profile is documented for scouting use. Applied to 2026, the screen surfaced: Braden Smith, Joshua Jefferson, Quadir Copeland, Gillespie, Lipsey, Duke Miles, Nkrumah.

### 8.3 Fragility of shooting-dependent top prospects (false positives)

Among the held-out **top-12 ranked players per class** (2020–23; n = 48: 21 hits, 27 misses), misses *out-shoot* hits while hits dominate the durable skills:

| Strength | Hits (mean pct) | Misses | Gap |
|---|---|---|---|
| Shooting | 46 | 57 | **−12** |
| Playmaking | 64 | 44 | **+20** |
| Rim pressure | 60 | 42 | **+18** |
| Perimeter defense | 59 | 42 | **+17** |

Define `fragility = shooting − ½(rim_pressure + perimeter_defense)`. Within top prospects: fragility alone separates misses at AUC 0.690; combined with model score, 0.799 → 0.824. **Permutation test p = 0.010; directionally positive in all four folds; bootstrap 90% CI on AUC [0.552, 0.815].** Globally (all 427 players) it adds nothing (bust AUC 0.913 vs 0.914) — the effect is conditional on already being ranked highly.

Interpretation: college 3P% is among the noisiest college stats; FT-rate and stocks are among the most stable. The pattern mirrors §8.2 from the opposite direction — playmaking, rim pressure, and defense are the durable currencies at the top of a draft. Worked examples (2024, graded so far): Dillingham (+54), Cody Williams (+39), Sheppard (+38), Knecht (+37) — all rotation-or-worse; Castle (−38) — star. Known false positive: Knueppel (+34, star).

**Status: not shipped as a model feature.** The discovery and test share the same 48 players (selection effect the p-value does not fully absorb), the magnitude is uncertain, and the sample is small. Assessed ~80% probability the effect is real with a most-likely modest magnitude. Recommended deployment: a visible warning flag on high-fragility top prospects, not a coefficient.

## 9. Rejected Hypotheses (the graveyard)

Each was implemented, tested under LOYO, and rejected. Recorded so they are not re-litigated.

| Hypothesis | Result | Held-out |
|---|---|---|
| Archetype fits as model features | No gain over strengths | ≤ baseline |
| `age × market` interaction | Identical held-out; fit on 12 first-round seniors; pushed validated seniors above equal-mock freshmen (made Lendeborg #1) | +0.815 vs +0.818 |
| **True draft-day age**, replacing class ordinal | Loses | +0.796 vs +0.821 |
| True age driving interactions | Loses | +0.803 |
| True age additive to ordinal | Loses | +0.804 |
| "Glue" feature (playmaking+defense composite) | No gain | flat |
| Fragility as global bust feature | No gain globally | 0.913 vs 0.914 |
| Bootstrap *parameter* averaging (intl, n=41) | Flattened all grades to a constant | — |
| Raw isotonic calibration | 0% bust at top (empty bin) | — |
| VORP/WS-based outcome tiers | Face-validity failures (Pritchard "star", Richards "starter") | — |

The true-age result is the most instructive: the class-year ordinal already carries the survivorship signal ("a freshman good enough to declare"), and continuous age — even measured to one decimal — added only noise. Intuition about features is routinely wrong; that is what the gate is for.

## 10. Limitations

1. **Feature ceiling.** One season of box score caps what is knowable; the six §8.2 misses are structural, not parametric.
2. **Selection bias.** Training only on draft entrants; development, opportunity, and landing spot are invisible.
3. **Market dependence at the margins.** Players absent from mock boards get market = 0, concentrating model risk exactly where statistics are noisiest.
4. **Selection-on-test-folds optimism.** Feature sets were chosen on the same four folds reported; headline +0.818 is mildly optimistic. The 2026 class is the only fully untouched test.
5. **Small-n subgroup analyses.** §8.3 in particular (n = 48) carries wide uncertainty and a researcher-degrees-of-freedom caveat.
6. **Young-class labels.** 2024–25 tiers are 1–2 season snapshots; they will move.
7. **International model** is thin (n = 41) with judgment-constant league tiers.

## 11. Conclusions

A position-relative, box-score outcome metric plus class-relative skill percentiles, a market-validation feature, and a conference tier — fit by bagged ridge and disciplined by leave-one-year-out validation — predicts NBA career value at +0.818 held-out Spearman, a ~3.3× improvement over the project's legacy score and materially better than the NBA draft order itself on the same populations. The probability layer provides calibrated boom/bust estimates (AUC 0.889/0.914). The system's documented blind spots are precisely characterized (glue players inbound, shooting-dependent stars outbound) and are mirror images of one another: **at the top of a draft, shooting is fragile; playmaking, rim pressure, and defense are durable.**

The single most valuable practice in this project was not any feature but the rule that nothing ships without held-out evidence — it rejected more of our ideas than it accepted, and every rejection is listed in §9.

---

## Appendix A: Reproduction

```bash
python -m analytics.value --rescore       # outcome metric -> result files
python -m analytics.strengths_model --save  # LOYO selection + bagged fit -> strengths_model.json
python -m analytics.predict               # calibrated boom/bust -> players.json
python -m analytics.intl_model            # international grades -> intl_model.json
python -m analytics.backtest              # validation harness
python -m data.scrape_ages                # Tankathon draft-day ages
python -m pytest                          # 66 tests incl. AUC floors + golden master
```

Key artifacts: `datasets/strengths_model.json` (coefficients, bands, validation numbers), `datasets/ages.json`, `datasets/intl_model.json`, `datasets/history/draft_results_*.json` (graded careers).
