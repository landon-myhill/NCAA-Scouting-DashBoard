"""
Backtest sanity tests — guard the analytics, not exact numbers.

These lock in that the formula still meaningfully predicts NBA value, so a
future formula edit that quietly destroys predictive power fails CI.
"""
import pytest

from analytics.backtest import load_matched, attach_blended_target, spearman
from model.archetypes import draft_score


@pytest.fixture(scope="module")
def rows():
    r = load_matched()
    attach_blended_target(r)
    return r


def test_evaluable_population_present(rows):
    # ~189 drafted players matched across 2020-2023; allow drift but not collapse.
    assert len(rows) > 150


def test_blended_target_in_unit_range(rows):
    for r in rows:
        assert r["target"] is None or 0.0 <= r["target"] <= 1.0


def test_formula_beats_zero_correlation(rows):
    """The live formula must predict NBA value clearly better than chance."""
    xs = [draft_score(r["college_record"]) for r in rows]
    ts = [r["target"] for r in rows]
    rho = spearman(xs, ts)
    assert rho is not None and rho > 0.30, f"pooled rho fell to {rho}"


def test_spearman_basic_properties():
    assert spearman([1, 2, 3, 4], [1, 2, 3, 4]) == pytest.approx(1.0)
    assert spearman([1, 2, 3, 4], [4, 3, 2, 1]) == pytest.approx(-1.0)
    assert spearman([1, 2], [1, 2]) is None  # too few points
