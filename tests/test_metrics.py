from __future__ import annotations

import math
from decimal import Decimal

import pytest

from dpa.eval.metrics import RunRecord, percentile, results_match, summarize
from dpa.types import QueryResult


def R(*rows, cols=None):
    width = len(rows[0]) if rows else 1
    return QueryResult(cols or tuple(f"c{i}" for i in range(width)), tuple(rows))


# --- results_match ------------------------------------------------------------------------


def test_same_rows_different_order():
    a, b = R(("US", 95.0), ("CN", 20.0)), R(("CN", 20.0), ("US", 95.0))
    assert results_match(a, b)
    assert not results_match(a, b, order_matters=True)


def test_column_names_ignored_and_columns_permuted():
    pred = R((95.0, "US"), (20.0, "CN"), cols=("total", "country"))
    gold = R(("US", 95.0), ("CN", 20.0), cols=("x", "y"))
    assert results_match(pred, gold)


def test_duplicates_count():
    assert not results_match(R((1,), (1,)), R((1,),))


def test_different_width_never_matches():
    assert not results_match(R(("US", 95.0, 1)), R(("US", 95.0)))


def test_numeric_tolerance_and_types():
    assert results_match(R((Decimal("0.1") + Decimal("0.2"),)), R((0.30000000001,)))
    assert results_match(R((3,)), R((3.0,)))
    assert not results_match(R((3.0,)), R((3.1,)))


def test_none_only_equals_none():
    assert results_match(R((None,)), R((None,)))
    assert not results_match(R((None,)), R((0,)))


def test_empty_results_match():
    assert results_match(QueryResult(("a",), ()), QueryResult(("b",), ()))


# --- percentile ---------------------------------------------------------------------------


@pytest.mark.parametrize("values, p, expected", [
    ([1, 2, 3, 4], 50, 2.5),
    (list(range(1, 101)), 95, 95.05),
    ([7], 95, 7),
    ([5, 1, 3], 0, 1),
    ([5, 1, 3], 100, 5),
])
def test_percentile(values, p, expected):
    assert math.isclose(percentile(values, p), expected)


@pytest.mark.parametrize("values, p", [([], 50), ([1], -1), ([1], 101)])
def test_percentile_rejects(values, p):
    with pytest.raises(ValueError):
        percentile(values, p)


# --- summarize ----------------------------------------------------------------------------


def rec(i, fast_ok, final_ok, corrected, first, final):
    return RunRecord(f"q{i}", fast_ok, final_ok, corrected, first, final)


def test_summarize():
    s = summarize([
        rec(1, True, True, False, 100, 100),
        rec(2, False, True, True, 110, 400),   # fixed
        rec(3, True, False, True, 120, 420),   # broke
        rec(4, False, False, False, 130, 130),
    ])
    assert (s.n, s.corrections, s.fixed, s.broke) == (4, 2, 1, 1)
    assert s.fast_accuracy == 0.5 and s.final_accuracy == 0.5
    assert math.isclose(s.p50_first_ms, 115)
    assert math.isclose(s.p50_final_ms, 265)
    assert math.isclose(s.p95_final_ms, percentile([100, 400, 420, 130], 95))


def test_summarize_empty():
    with pytest.raises(ValueError):
        summarize([])
