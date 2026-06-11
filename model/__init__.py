"""
model — the scoring/classification engine.

    archetypes.py       draft_score() + classify() + DEFAULT_WEIGHTS (data-fit)
    rerank.py           score + classify + scarcity for the current season
    rerank_history.py   re-score historical seasons with the current formula

Run the rerankers as modules from the repo root:
    python -m model.rerank
    python -m model.rerank_history
"""
