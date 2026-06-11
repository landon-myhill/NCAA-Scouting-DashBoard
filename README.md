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

Built 100% from college stats. The composite blends component scores (production, impact, two-way, elite metrics, size, length, playmaking, FT touch, recruit pedigree) scaled by conference / class-year / position multipliers. Components are **position-fair**: elite-metric bars sit at each position's own 75th/90th percentile and steals+blocks are scaled per position, so guards and bigs qualify at comparable rates. **The blend weights are data-fit, not hand-tuned** — ridge regression against real NBA outcomes on the 2020–2023 classes, validated leave-one-year-out.

### NBA outcomes (the measuring stick — never an input to the score)

Careers are graded with a **position-relative box-score value** (`analytics/value.py`): career PPG / minutes-per-game / RPG / APG / durability, each percentiled within position group and per-season — no VORP/WS composites (they misgrade roles: durable backup bigs farm Win Shares, bad-team starters grade as benchwarmers). Career tiers (star / starter / rotation / bench / no_nba) are bands on that score; classes younger than 3 seasons show "early career" instead of a premature tier. The formula's held-out rank correlation vs this target is **+0.30**, and the actual NBA draft order scores comparably — a box-score model performing at parity with the scouting industry.

### Boom / Bust (the projection)

`analytics/predict.py` calibrates the draft score into probabilities, validated leave-one-year-out against the box-score outcome tiers: **Boom** = P(NBA starter or better), held-out AUC **0.68**; **Bust** = P(bench or out of the league), AUC **0.61**. Multi-feature models were tested and scored worse — they don't ship (same rule as everything else: held-out improvement or it doesn't go in).

Honesty caveats baked in: outcome data covers drafted players (plus scraped undrafted top-150 outcomes via `data/scrape_undrafted.py`), so probabilities read as "for a draftable-caliber prospect"; any change must improve held-out CV *and* pass face-validity spot checks before shipping.

Re-tune: `python -m analytics.tune`. Baseline check: `python -m analytics.backtest`. Re-grade outcomes: `python -m analytics.value --rescore`.

## Testing

```bash
python -m pytest        # or: python pipeline.py test
```

The suite includes a **golden-master** lock on `draft_score` — if any refactor changes a player's score, the test fails loudly. Plus held-out AUC floors for the Boom/Bust heads, name-matching, numeric parsing, scrape-schema validation, and a backtest floor on predictive power.
