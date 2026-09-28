"""Checking the judge: agreement with human labels and calibration of its confidence.

Used for answers that cannot be execution-matched: a model grades them, and these functions
measure whether that grader can be trusted, against a hand-labelled sample.

TODO(Changqi): implement. Tests: tests/test_judge.py.
"""

from __future__ import annotations

from collections.abc import Hashable, Sequence


def cohens_kappa(a: Sequence[Hashable], b: Sequence[Hashable]) -> float:
    """Cohen's kappa between two raters labelling the same items.

    kappa = (p_o - p_e) / (1 - p_e), with p_e from each rater's marginal label frequencies.
    If p_e == 1 (both raters used one identical label throughout) return 1.0.
    Raises: ValueError if the sequences differ in length or are empty.
    """
    raise NotImplementedError


def expected_calibration_error(
    confidences: Sequence[float], correct: Sequence[bool], n_bins: int = 10
) -> float:
    """ECE with n_bins equal-width bins over [0, 1].

    Bin i covers (i/n_bins, (i+1)/n_bins]; a confidence of exactly 0 goes in bin 0.
    ECE = sum over non-empty bins of (bin_size / N) * |mean confidence - accuracy|.
    Raises: ValueError on length mismatch, empty input, or a confidence outside [0, 1].
    """
    raise NotImplementedError
