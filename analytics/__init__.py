"""
analytics — evaluation, tuning, and prediction against real NBA outcomes.

    backtest.py   shared eval harness: match draftees to college seasons,
                  blended NBA-value target, Spearman, evaluate()
    tune.py       ridge-fit the draft-score blend (leave-one-year-out CV)
    predict.py    ML success/bust probability model -> players.json
    history.py    formula vs actual draft outcomes (steals/reaches report)
    traits.py     which college stats separate NBA stars from busts
    stars.py      college profile of a curated top-100 NBA stars list
    reports.py    optional LLM scouting reports via local Ollama

Run as modules from the repo root, e.g. `python -m analytics.tune`.
"""
