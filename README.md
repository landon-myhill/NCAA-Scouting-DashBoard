# NCAA Draft Scout

A Streamlit-based scouting app for NCAA D1 basketball prospects. Scrapes real stats from sports-reference.com, classifies players into archetypes, and ranks them using a composite draft score.

## Quick Start

```bash
# 1. Install dependencies
pip install -r requirements.txt

# 2. Scrape player data (~12 min, only need to run once)
python scrape.py

# 3. Apply draft rankings
python rerank.py

# 4. Launch the app
streamlit run app.py
```

The app opens at http://localhost:8501.

## How It Works

### Data Pipeline

1. **`scrape.py`** — Scrapes all 365 D1 school pages from sports-reference.com. Collects per-game stats (PPG, RPG, APG, SPG, BPG, FG%, 3P%, FT%, MPG, TOV, etc.), advanced metrics (PER, TS%, BPM, Win Shares, etc.), and roster info (height, weight, class year, hometown). Saves everything to `players.json`.

2. **`rerank.py`** — Reads `players.json` and re-sorts players using a composite draft score that weighs production, efficiency, impact, two-way ability, age, conference strength, position value, and size. Updates ranks and tiers in place.

3. **`archetypes.py`** — Classifies each player into a primary archetype (e.g., Floor General, Three-Level Scorer, Rim Protector), a defensive archetype (e.g., Perimeter Pest, Paint Presence), trait tags, and red flags. Also contains the `draft_score()` function used by `rerank.py`.

4. **`app.py`** — The Streamlit app that reads `players.json` and displays everything.

### App Features

- **Scouting** — Player header, archetype badges, trait/concern tags, radar skill chart, scout notes, season stats, advanced metrics
- **Compare** — Compare 2-5 players side by side with overlaid radar charts and a stat table that highlights the best value per stat
- **Big Board** — Three-tier draft board (Lottery / Late 1st / 2nd Round) with move-up/move-down controls, draft scores, and CSV export
- **Watchlist** — Star players to track them, with stat cards, notes preview, and CSV export
- **Scarcity** — Archetype scarcity analysis with adjustable player pool, stacked bar charts, draft score box plots, positional gap detection, and conference archetype production

### Sidebar

- **Search** — Type a name, school, or conference to filter the player dropdown
- **Filters** — Filter by position, conference, or primary archetype
- **Data Source** — Switch between scraped data and live NCAA API (limited to PPG/RPG/APG)

## Re-scraping

Run `python scrape.py` again to refresh data. It uses a 2-second delay between requests to avoid rate limiting. If you get blocked (HTTP 429), wait 1-2 hours and try again.

After scraping, always run `python rerank.py` to apply the draft score rankings.

## Files

| File | Purpose |
|------|---------|
| `app.py` | Streamlit app |
| `scrape.py` | Sports-reference scraper |
| `rerank.py` | Draft score ranking |
| `archetypes.py` | Player classification & draft scoring |
| `players.json` | Scraped player data (generated) |
| `requirements.txt` | Python dependencies |
