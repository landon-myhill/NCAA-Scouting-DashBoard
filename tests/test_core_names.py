"""Tests for core.names — normalization, matching, and stable ids."""
from core.names import normalize_name, name_keys, stable_id, match_player


def test_normalize_strips_accents_suffixes_punct():
    assert normalize_name("Kasparas Jakučionis Jr.") == "kasparas jakucionis"
    assert normalize_name("D'Angelo Russell II") == "dangelo russell"
    assert normalize_name("  Multiple   Spaces ") == "multiple spaces"
    assert normalize_name(None) == ""


def test_name_keys_initial_fallback():
    full, initial = name_keys("Louis Hutchinson")
    assert full == "louis hutchinson"
    assert initial == "l hutchinson"


def test_stable_id_is_deterministic_and_identity_based():
    # Same identity (modulo formatting) -> same id.
    assert stable_id("Cooper Flagg", "Duke") == stable_id("cooper  flagg", "duke")
    # Different identity -> (almost surely) different id.
    assert stable_id("Cooper Flagg", "Duke") != stable_id("Cooper Flagg", "Kansas")
    # Always a positive 31-bit int.
    pid = stable_id("A B", "C")
    assert 0 < pid <= 0x7FFFFFFF


def test_stable_id_unique_across_a_realistic_roster():
    names = [(f"Player {i}", "School A") for i in range(500)]
    ids = {stable_id(n, s) for n, s in names}
    assert len(ids) == 500  # no collisions at this scale


def _index(players):
    by_norm = {normalize_name(p["name"]): p for p in players}
    by_school = {}
    for p in players:
        by_school.setdefault(p.get("school", ""), []).append(p)
    return by_norm, by_school


def test_match_player_exact_and_fallback():
    players = [
        {"name": "Cade Cunningham", "school": "Oklahoma State"},
        {"name": "Louis Hutchinson", "school": "Pitt"},
    ]
    by_norm, by_school = _index(players)
    # exact
    assert match_player({"player": "Cade Cunningham"}, by_norm, by_school)["school"] == "Oklahoma State"
    # nickname / first-initial fallback
    assert match_player({"player": "Lou Hutchinson"}, by_norm, by_school)["name"] == "Louis Hutchinson"
    # no match
    assert match_player({"player": "Nobody Here"}, by_norm, by_school) is None
