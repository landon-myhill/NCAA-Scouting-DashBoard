"""
Scoring tests — including a GOLDEN-MASTER lock.

The golden test pins draft_score() outputs for a fixed sample of real players.
If a refactor changes any score, this fails loudly — exactly what you want for
a ranking engine whose value IS the numbers. Regenerate the fixture only when a
score change is intentional (see tests/fixtures/golden_scores.json).
"""
import json
from pathlib import Path

import pytest

from model.archetypes import draft_score, combine_parts, DEFAULT_WEIGHTS

GOLDEN = Path(__file__).parent / "fixtures" / "golden_scores.json"


@pytest.fixture(scope="module")
def golden():
    return json.loads(GOLDEN.read_text(encoding="utf-8"))


def test_golden_master_scores_unchanged(golden):
    """Every sampled player must still score exactly what was locked."""
    mismatches = []
    for g in golden:
        got = round(draft_score(g["record"]), 2)
        if got != g["expected_score"]:
            mismatches.append(f"{g['name']}: expected {g['expected_score']}, got {got}")
    assert not mismatches, "Scoring drift detected:\n" + "\n".join(mismatches)


def test_golden_ordering_preserved(golden):
    """The sampled players, sorted by score, keep their locked relative order."""
    expected = [g["name"] for g in sorted(golden, key=lambda g: -g["expected_score"])]
    actual = [g["name"] for g in sorted(golden, key=lambda g: -draft_score(g["record"]))]
    assert actual == expected


def test_return_parts_recombines_to_score(golden):
    """combine_parts(parts) must reproduce the default draft_score (single
    source of truth — the /ranking page depends on this)."""
    for g in golden:
        rec = g["record"]
        direct = round(draft_score(rec), 2)
        recombined = round(combine_parts(draft_score(rec, return_parts=True)), 2)
        assert direct == recombined, g["name"]


def test_parts_has_all_weight_keys(golden):
    parts = draft_score(golden[0]["record"], return_parts=True)
    for key in ["prod", "eff", "impact", "two_way", "play", "ft", "min", "tov",
                "size", "anthro", "elite", "recruit",
                "age_mult", "conf_mult", "pos_mult"]:
        assert key in parts


def test_efficiency_weight_is_negative():
    """Documents the key data-fit finding: efficiency is counter-predictive."""
    assert DEFAULT_WEIGHTS["eff"] < 0


def test_draft_score_handles_empty_player():
    """Must not crash on a sparse record (missing stats/advanced)."""
    assert isinstance(draft_score({"pos": "G", "stats": {}, "advanced": {}}), float)
