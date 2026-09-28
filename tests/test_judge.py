from __future__ import annotations

import math

import pytest

from dpa.eval.judge import cohens_kappa, expected_calibration_error


def test_kappa_perfect_agreement():
    assert cohens_kappa(["y", "n", "y"], ["y", "n", "y"]) == 1.0


def test_kappa_hand_computed():
    # p_o = 3/4; p_e = 0.5*0.25 + 0.5*0.75 = 0.5  ->  kappa = 0.5
    assert math.isclose(cohens_kappa([1, 1, 0, 0], [1, 0, 0, 0]), 0.5)


def test_kappa_chance_level_is_zero():
    assert math.isclose(cohens_kappa([1, 1, 0, 0], [1, 0, 1, 0]), 0.0)


def test_kappa_degenerate_single_label():
    assert cohens_kappa(["y", "y"], ["y", "y"]) == 1.0


@pytest.mark.parametrize("a, b", [([], []), ([1], [1, 0])])
def test_kappa_rejects(a, b):
    with pytest.raises(ValueError):
        cohens_kappa(a, b)


def test_ece_perfectly_calibrated_is_zero():
    assert math.isclose(expected_calibration_error([0.8] * 10, [True] * 8 + [False] * 2), 0.0,
                        abs_tol=1e-12)


def test_ece_overconfident():
    assert math.isclose(expected_calibration_error([0.9, 0.9], [False, False]), 0.9)


def test_ece_two_bins_weighted():
    # bin (0.1,0.2]: conf 0.2, acc 0 -> gap 0.2, weight 1/2
    # bin (0.9,1.0]: conf 1.0, acc 1 -> gap 0,   weight 1/2
    assert math.isclose(expected_calibration_error([0.2, 1.0], [False, True]), 0.1)


def test_ece_zero_confidence_goes_in_first_bin():
    assert math.isclose(expected_calibration_error([0.0], [False]), 0.0)


@pytest.mark.parametrize("conf, ok", [([], []), ([0.5], [True, False]), ([1.2], [True])])
def test_ece_rejects(conf, ok):
    with pytest.raises(ValueError):
        expected_calibration_error(conf, ok)
