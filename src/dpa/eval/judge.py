"""Checking the judge: agreement with human labels and calibration of its confidence.

Used for answers that cannot be execution-matched: a model grades them, and these functions
measure whether that grader can be trusted, against a hand-labelled sample.

Tests: tests/test_judge.py.
"""

from __future__ import annotations

import math
from collections import Counter
from collections.abc import Hashable, Sequence


def cohens_kappa(a: Sequence[Hashable], b: Sequence[Hashable]) -> float:
    """Cohen's kappa between two raters labelling the same items.

    kappa = (p_o - p_e) / (1 - p_e), with p_e from each rater's marginal label frequencies.
    If p_e == 1 (both raters used one identical label throughout) return 1.0.
    Raises: ValueError if the sequences differ in length or are empty.
    """
    if len(a) != len(b):
        raise ValueError("raters must label the same number of items")
    if not a:
        raise ValueError("kappa is undefined for empty label sequences")
    count = len(a)
    observed = sum(left == right for left, right in zip(a, b)) / count
    frequencies_a = Counter(a)
    frequencies_b = Counter(b)
    expected = sum(
        frequencies_a[label] * frequencies_b[label] / (count * count)
        for label in frequencies_a.keys() | frequencies_b.keys()
    )
    if expected == 1:
        return 1.0
    return (observed - expected) / (1 - expected)


def expected_calibration_error(
    confidences: Sequence[float], correct: Sequence[bool], n_bins: int = 10
) -> float:
    """ECE with n_bins equal-width bins over [0, 1].

    Bin i covers (i/n_bins, (i+1)/n_bins]; a confidence of exactly 0 goes in bin 0.
    ECE = sum over non-empty bins of (bin_size / N) * |mean confidence - accuracy|.
    Raises: ValueError on length mismatch, empty input, or a confidence outside [0, 1].
    """
    if len(confidences) != len(correct):
        raise ValueError("confidences and labels must have the same length")
    if not confidences:
        raise ValueError("ECE is undefined for empty input")
    if isinstance(n_bins, bool) or not isinstance(n_bins, int) or n_bins <= 0:
        raise ValueError("n_bins must be a positive integer")
    if any(not 0 <= confidence <= 1 for confidence in confidences):
        raise ValueError("confidence values must be in [0, 1]")

    bin_values: list[list[tuple[float, bool]]] = [[] for _ in range(n_bins)]
    for confidence, is_correct in zip(confidences, correct):
        index = 0 if confidence == 0 else min(n_bins - 1, math.ceil(confidence * n_bins) - 1)
        bin_values[index].append((confidence, is_correct))

    total = len(confidences)
    error = 0.0
    for values in bin_values:
        if not values:
            continue
        mean_confidence = sum(confidence for confidence, _ in values) / len(values)
        accuracy = sum(is_correct for _, is_correct in values) / len(values)
        error += len(values) / total * abs(mean_confidence - accuracy)
    return error
