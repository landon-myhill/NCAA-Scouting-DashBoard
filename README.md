# NCAA Draft Scout

A Flask-based scouting dashboard for NCAA D1 basketball prospects. Scrapes real stats from sports-reference.com, classifies players into multiple archetypes, ranks them with a data-fit composite draft score, and projects each prospect's **Boom % / Bust %** with an ML model trained on real NBA career outcomes.

## Features

- **Scouting** — Player profiles with archetype badges, Boom/Bust projection, skill radar charts, scouting tags, auto-saving notes, full stats and advanced metrics
- **Compare** — Search and compare up to 10 players with overlaid radar charts and best-value stat highlighting
- **Big Board** — Drag-and-drop draft board for the top 200 prospects with instant position/conference filters and per-player Boom/Bust
- **Watchlist** — Persistent watchlist with notes, stored in SQLite
- **Scarcity** — Archetype depth analysis with charts, positional gaps, and conference production breakdowns
- **Team Needs** — Select the archetypes your team is missing and get ranked prospect recommendations with fit percentages

## Quick Start

```bash
# 1. Install dependencies
pip install -r requirements.txt

# 2. Rebuild boards + predictions from the committed data (no scraping needed)
python pipeline.py build

# 3. Launch the app
python app.py
```

The app opens at http://localhost:5001 (set `SCOUT_DEBUG=1` for dev auto-reload).

To refresh everything from the web instead (slow, ~15 min):

```bash
python pipeline.py scrape    # scrape -> parse -> merge -> rerank -> predict
```

Run `python pipeline.py --plan` to see the full pipeline DAG.

## Project Structure

```
app.py            Entry point (`python app.py`); the app lives in web/
pipeline.py       Runs the data DAG (build | scrape | test | --plan)

core/             Shared foundation — import from here, never re-define helpers
  config.py         Season year, every file path, constants (single source of truth)
  names.py          Name normalization, matching, STABLE player ids
  numeric.py        Robust stat parsing (flt, pct, height, safe_stat)
  jsonio.py         JSON load/save helpers
  validation.py     Scrape sanity checks (schema, null-rate, row count)

data/             Acquisition: scrapers, parsers, merge steps (python -m data.<name>)
model/            Scoring engine: archetypes.py (draft_score + classify), rerank*
analytics/        Evaluation + prediction vs real NBA outcomes
  backtest.py       Eval harness: blended NBA-value target, Spearman, evaluate()
  tune.py           Ridge-fit the score weights (leave-one-year-out CV)
  predict.py        ML Boom/Bust probabilities -> players.json
  history.py        Formula vs actual draft results (steals/reaches report)
  traits.py         Which college stats separate NBA stars from busts
  stars.py          College profile of a curated top-100 NBA stars list
  reports.py        Optional LLM scouting reports via local Ollama

web/              The Flask app: store (data), db (SQLite), views, api, charts
datasets/         ALL data files: players.json, scarcity.json, scouting.db,
                  draft_eligible.json, stars_list.json, history/, combine/, recruits/
  board_lists/      Optional curated big boards: board_<year>.txt ("Name | School"
                    per line). When present, that season's big board shows ONLY
                    those players. Names with no NCAA record (international,
                    G-League, injured) appear in a marked section at the bottom —
                    with real NBA outcomes on historical boards, and with scraped
                    international stats (datasets/intl/, via data/scrape_intl.py)
                    on the current board.
scripts/          One-shot migrations (migrate_ids)
templates/ static/  HTML templates · CSS/JS
tests/            pytest suite — run `python -m pytest`
```

## How It Works

### Data Pipeline (`python pipeline.py --plan`)

1. **ACQUIRE** (network) — `data/scrape*` pull current + historical seasons, draft entrants, NBA draft results/careers, and HS recruit ranks; `data/parse_*` normalize raw files.
2. **BUILD** (local) — `data/merge_*` stamp recruit rank + combine measurements onto players; `model/rerank*` score, classify archetypes, and build scarcity; `analytics/predict` stamps Boom/Bust probabilities.
3. **`web/`** serves it all with SQLite persistence for watchlist, notes, and board order.

### Draft Score (the ranking)

The composite draft score blends component scores scaled by conference / class-year / position multipliers. **The blend weights are data-fit, not hand-tuned** — ridge regression of the components against real NBA career value (Win Shares + VORP + career tier) on the 2020–2023 draft classes, validated with leave-one-year-out cross-validation. Held-out rank correlation vs NBA value: **+0.358** (prior hand-tuned formula: +0.339).

What the fit learned (strongest → weakest NBA-success predictors):
- **Size, elite advanced metrics, HS recruit rank, two-way value, win-share impact** — the real drivers
- **Production** (PPG/RPG/APG) — modest signal once the above are in
- **Efficiency** (PER/TS%/eFG%) — *negative* weight: adds noise, not signal
- **Conference & class-year** — kept as multipliers (essential for full-board calibration)

Re-tune: `python -m analytics.tune`. Baseline check: `python -m analytics.backtest`.

### Boom / Bust (the projection)

`analytics/predict.py` adds two probabilities per player, learned from what actually happened to the 2020–2023 drafted classes (mature careers only) and validated leave-one-year-out:

- **Boom** = P(NBA starter or better). A 1-D logistic calibration of the draft score itself (held-out AUC **0.70**). A multi-feature model scored *worse* — the formula's multiplicative structure already ranks upside best, so we convert it to a probability instead of re-learning it badly.
- **Bust** = P(bench or out of the league). A logistic model on the score components + size (held-out AUC **0.73** vs 0.68 for the score alone) — downside risk has extra signal in the *shape* of the profile (efficiency-only producers, no defensive events, weak frame) that a rank can't see.

Honesty caveats baked into the design: we only observe NBA outcomes for **drafted** players, so probabilities read as "if this player is a drafted-caliber prospect"; and any change must improve held-out CV *and* pass the full-board sanity check (mid-major count, position split, recognizable top recruits) before shipping.

## Testing

```bash
python -m pytest        # or: python pipeline.py test
```

The suite includes a **golden-master** lock on `draft_score` — if any refactor changes a player's score, the test fails loudly. Plus held-out AUC floors for the Boom/Bust heads, name-matching, numeric parsing, scrape-schema validation, and a backtest floor on predictive power.
