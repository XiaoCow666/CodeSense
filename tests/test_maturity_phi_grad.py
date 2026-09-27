"""Regression tests for ``phi_grad`` in ``utils/maturity_calculator.py``.

The growth-gradient component averages the first and second halves of a
student's chronological submissions. ``Submission.score`` is a percentage
(0–100) and nullable (``models.py`` declares ``score = db.Column(db.Integer)``
with no default), because a submitted-but-not-yet-evaluated submission has no
score. The maturity formula works on the historical 0–5 scale, so scores are
converted inside the formula via ``normalize_mixed_score(...) / 20``.

The buggy implementation filtered unscored rows out of the *numerator* but
divided by the full half length, so an unscored submission silently counted as
zero. When the two halves have different missing-score rates, the reported
gradient was not just off but could have the wrong sign (e.g. real improvement
40 -> 43 reported as a decline).

These tests use lightweight in-memory fakes: no Flask app, database, Redis,
or network.
"""
from datetime import datetime, timedelta

import pytest

from utils.maturity_calculator import calculate_maturity_components


class _Sub:
    """Minimal stand-in for the Submission rows the function reads."""

    def __init__(self, score, submitted_at):
        self.score = score
        self.submitted_at = submitted_at


def _subs(scores):
    # Spaced one day apart; only relative order and values matter.
    start = datetime.now() - timedelta(days=len(scores))
    return [_Sub(score, start + timedelta(days=i)) for i, score in enumerate(scores)]


def _phi_grad(scores):
    return calculate_maturity_components(_subs(scores))["phi_grad"]


# ---------------------------------------------------------------------------
# regression: unscored submissions must be excluded, not counted as zero
# ---------------------------------------------------------------------------

def test_phi_grad_excludes_unscored_submission_in_recent_half():
    # Real trajectory: scored halves are 40 and 43 (percent). In the 0–5
    # scale that is 2.00 vs 2.15, growth +0.15 -> 50 + 1.5 = 51.5.
    # Before the fix the recent half divided by 2 (None counted as zero),
    # averaging 1.075, growth -0.925, and phi_grad read 40.75 (a decline).
    assert _phi_grad([40, 40, None, 43]) == pytest.approx(51.5)


def test_phi_grad_excludes_unscored_submission_in_first_half():
    # Mirror case: scored first half 43, recent half 40, growth -0.15 -> 48.5.
    # Before the fix the first half averaged 1.075, so a mild decline was
    # reported as growth (59.25).
    assert _phi_grad([None, 43, 40, 40]) == pytest.approx(48.5)


def test_phi_grad_normal_path_unchanged():
    # All submissions scored: behavior must be identical to before.
    # 0–5 scale: 2.0 vs 4.0, growth +2 -> 70.
    assert _phi_grad([40, 40, 80, 80]) == 70


def test_phi_grad_flat_trajectory_is_neutral():
    # No change -> the neutral gradient value 50.
    assert _phi_grad([60, 60, 60, 60]) == 50


# ---------------------------------------------------------------------------
# boundary: nothing to compare against -> neutral default, never a crash
# ---------------------------------------------------------------------------

def test_phi_grad_neutral_when_no_scored_submissions():
    # Division by the scored count must be guarded. The function has no
    # evidence for growth, so it must keep the neutral 50 instead of raising
    # ZeroDivisionError on the empty score lists.
    assert _phi_grad([None, None, None, None]) == 50


def test_phi_grad_neutral_when_one_half_has_no_scores():
    # First half entirely unscored: no valid first-half mean exists.
    # Before the fix it was treated as 0 vs a 4.0 recent mean -> phi 90.
    assert _phi_grad([None, None, 80, 80]) == 50


def test_phi_grad_neutral_when_fewer_than_four_submissions():
    # Pre-existing rule: the gradient needs two comparable halves.
    assert _phi_grad([40, 90]) == 50


def test_zero_scores_are_real_scores_not_dropped():
    # 0 is a legitimate value, not a missing score. It participates as zero:
    # first-half mean (0+4)/2 = 2.0 vs recent 4.0, growth +2 -> 70.
    assert _phi_grad([0, 80, 80, 80]) == 70
