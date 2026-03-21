# NCAA Draft Scout

A Flask-based scouting dashboard for NCAA D1 basketball prospects. Scrapes real stats from sports-reference.com, classifies players into multiple archetypes, and ranks them using a composite draft score.

![Scouting](screenshots/Scout_1.png)

![Big Board](screenshots/BigBoard.png)

> **[See the full walkthrough with all screenshots](WALKTHROUGH.md)**

## Quick Start

```bash
# 1. Install dependencies
pip install -r requirements.txt

# 2. Scrape player data (~12 min, only need to run once)
python scrape.py

# 3. Apply draft rankings + classify archetypes + build scarcity data
python rerank.py

# 4. Launch the app
python app.py
```

The app opens at http://localhost:5001.

## Features

- **Scouting** — Player profiles with archetype badges, skill radar charts, scouting tags, auto-saving notes, full stats and advanced metrics
- **Compare** — Search and compare up to 10 players with overlaid radar charts and best-value stat highlighting
- **Big Board** — Drag-and-drop draft board for the top 200 prospects with instant position/conference filters
- **Watchlist** — Persistent watchlist with notes, stored in SQLite
- **Scarcity** — Archetype depth analysis with charts, positional gaps, and conference production breakdowns
- **Team Needs** — Select the archetypes your team is missing and get ranked prospect recommendations with fit percentages

## How It Works

### Data Pipeline

1. **`scrape.py`** — Scrapes all 365 D1 school pages from sports-reference.com. Collects per-game stats, advanced metrics, and roster info. Saves to `players.json`.

2. **`rerank.py`** — Re-sorts players using a composite draft score. Classifies every player into all qualifying archetypes, generates trait tags and red flags, and pre-builds `scarcity.json`.

3. **`archetypes.py`** — Classifies players into offensive archetypes (e.g., Three-Level Scorer, Combo Guard) and defensive archetypes (e.g., Wing Stopper, Point of Attack Defender). Players can have multiple archetypes — no fallbacks, you either qualify or you don't.

4. **`app.py`** — Flask web app with SQLite persistence for watchlist, scout notes, and board order.

### Draft Score Formula

The composite draft score weighs:
- **Production (38%)** — PPG, RPG, APG, SPG, BPG with position-specific caps
- **Efficiency (25%)** — PER, TS%, BPM, eFG%
- **Impact (15%)** — Win Shares, WS/40
- **Two-Way (10%)** — DBPM, DWS, stocks
- **Multipliers** — Class year (Freshman 1.22x, Senior 0.85x), conference strength, position value, size adjustment

## Files

| File | Purpose |
|------|---------|
| `app.py` | Flask web app |
| `scrape.py` | Sports-reference scraper |
| `rerank.py` | Draft score ranking, archetype classification, scarcity pre-computation |
| `archetypes.py` | Player classification & draft scoring engine |
| `players.json` | Full player database (generated) |
| `scarcity.json` | Pre-computed scarcity data for top 200 (generated) |
| `scouting.db` | SQLite database for notes, watchlist, board order (auto-created) |
| `templates/` | HTML templates |
| `static/` | CSS and JavaScript |
