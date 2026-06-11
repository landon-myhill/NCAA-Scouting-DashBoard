"""Tests for core.validation — the scrape sanity gate."""
import pytest

from core.validation import validate_players, DataValidationError


def _good_player(i):
    return {
        "name": f"Player {i}", "pos": "G", "school": "S", "conference": "ACC",
        "year": "Freshman", "id": i,
        "stats": {"PPG": 10, "RPG": 4, "APG": 3, "MPG": 25, "FG%": 45},
        "advanced": {"PER": 18, "TS%": 55, "BPM": 3, "Win Shares": 2},
    }


def test_good_data_passes():
    players = [_good_player(i) for i in range(2500)]
    assert validate_players(players) == []


def test_too_few_players_fails():
    with pytest.raises(DataValidationError):
        validate_players([_good_player(i) for i in range(10)])


def test_missing_keys_flagged():
    players = [_good_player(i) for i in range(2500)]
    for p in players[:60]:
        del p["advanced"]
    with pytest.raises(DataValidationError):
        validate_players(players)


def test_high_null_rate_flagged():
    players = [_good_player(i) for i in range(2500)]
    for p in players:  # wipe a core stat for everyone -> layout-change signal
        p["stats"]["PPG"] = None
    with pytest.raises(DataValidationError):
        validate_players(players)


def test_duplicate_ids_flagged():
    players = [_good_player(i) for i in range(2500)]
    players[1]["id"] = players[0]["id"]
    with pytest.raises(DataValidationError):
        validate_players(players)


def test_non_strict_returns_warnings():
    problems = validate_players([_good_player(0)], strict=False)
    assert problems and any("players" in p for p in problems)
