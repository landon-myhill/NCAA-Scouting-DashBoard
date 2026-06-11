"""
Prediction-layer sanity tests — guard predictive power, not exact numbers.

Locks in that the success/bust heads still beat chance on held-out years, so
a formula or feature change that quietly destroys the ML layer fails CI.
"""
import numpy as np
import pytest

from analytics.backtest import attach_value_target, load_matched
from analytics.predict import loyo_cv, train_final


@pytest.fixture(scope="module")
def rows():
    r = load_matched()
    attach_value_target(r)
    return r


@pytest.fixture(scope="module")
def cv(rows):
    return loyo_cv(rows)


def test_success_head_beats_chance_held_out(cv):
    mean_auc = np.mean([m["auc_success"] for m in cv.values()])
    assert mean_auc > 0.60, f"success AUC fell to {mean_auc:.3f}"


def test_bust_head_beats_chance_held_out(cv):
    mean_auc = np.mean([m["auc_bust"] for m in cv.values()])
    assert mean_auc > 0.60, f"bust AUC fell to {mean_auc:.3f}"


def test_probabilities_are_valid_and_ordered(rows):
    """Final-fit probabilities live in [0,1]; as a GROUP, players who actually
    succeeded must project higher success / lower bust than players who busted.
    (Individual pairs can legitimately invert — e.g. Haliburton's skinny
    low-usage college profile screamed bust risk and he hit anyway.)"""
    head_s, head_b = train_final(rows)
    recs = [r["college_record"] for r in rows]
    ps, pb = head_s.prob(recs), head_b.prob(recs)
    assert ((0.0 <= ps) & (ps <= 1.0)).all() and ((0.0 <= pb) & (pb <= 1.0)).all()

    hit = [i for i, r in enumerate(rows) if r["tier_val"] >= 3]
    bust = [i for i, r in enumerate(rows) if r["tier_val"] <= 1]
    assert np.mean(ps[hit]) > np.mean(ps[bust])
    assert np.mean(pb[hit]) < np.mean(pb[bust])
