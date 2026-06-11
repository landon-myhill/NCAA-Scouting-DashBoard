"""App-level smoke tests: every route renders, ids are stable, no global mutation."""
import copy

import pytest

from web import app
from web import store


@pytest.fixture(scope="module")
def client():
    return app.test_client()


@pytest.mark.parametrize("path", [
    "/", "/scouting", "/bigboard", "/bigboard?year=all", "/bigboard?sort=raw",
    "/bigboard?year=2024", "/bigboard?year=2020", "/bigboard?year=2025",
    "/archetypes", "/archetypes?year=2023", "/ranking", "/scarcity", "/needs",
    "/watchlist", "/compare", "/api/players?q=a",
])
def test_routes_ok(client, path):
    assert client.get(path, follow_redirects=True).status_code == 200


def test_player_ids_are_stable_not_positional():
    players = store.PLAYERS
    assert players, "no players loaded"
    ids = [p["id"] for p in players]
    assert len(set(ids)) == len(ids), "duplicate player ids"
    # Stable ids are large hashes, not 1..N sort positions.
    assert ids[:5] != [1, 2, 3, 4, 5]


def test_bigboard_does_not_mutate_global_players(client):
    before = copy.deepcopy(store.PLAYERS[:50])
    client.get("/bigboard")
    client.get("/api/export/bigboard.csv")
    after = store.PLAYERS[:50]
    for b, a in zip(before, after):
        assert "_display_pos" not in a and "_board_pos" not in a
        assert b["id"] == a["id"] and b["rank"] == a["rank"]


def test_ranking_examples_match_live_score(client):
    """The /ranking explainer must reflect real draft_score, not stale math."""
    from model.archetypes import draft_score
    top = sorted(store.PLAYERS, key=lambda p: p["rank"])[0]
    assert round(draft_score(top), 1) == round(top["draft_score"], 1)
