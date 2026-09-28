"""Accuracy and latency metrics.

Tests: tests/test_metrics.py.
"""

from __future__ import annotations

import itertools
import math
from collections.abc import Sequence
from dataclasses import dataclass
from decimal import Decimal, DecimalException
from typing import Any

from dpa.types import QueryResult


def _is_number(value: Any) -> bool:
    return isinstance(value, (int, float, Decimal)) and not isinstance(value, bool)


def _values_equal(left: Any, right: Any, rel_tol: float) -> bool:
    if left is None or right is None:
        return left is None and right is None
    if _is_number(left) and _is_number(right):
        try:
            left_decimal = left if isinstance(left, Decimal) else Decimal(str(left))
            right_decimal = right if isinstance(right, Decimal) else Decimal(str(right))
            if not left_decimal.is_finite() or not right_decimal.is_finite():
                return left_decimal == right_decimal
            tolerance = Decimal(str(rel_tol))
            scale = max(abs(left_decimal), abs(right_decimal))
            return abs(left_decimal - right_decimal) <= tolerance * scale
        except DecimalException:
            return left == right
    return left == right


def _rows_equal(left: tuple[Any, ...], right: tuple[Any, ...], rel_tol: float) -> bool:
    return len(left) == len(right) and all(
        _values_equal(a, b, rel_tol) for a, b in zip(left, right)
    )


def _multiset_matches(
    predicted: tuple[tuple[Any, ...], ...],
    expected: tuple[tuple[Any, ...], ...],
    rel_tol: float,
) -> bool:
    edges = [
        [index for index, row in enumerate(expected) if _rows_equal(candidate, row, rel_tol)]
        for candidate in predicted
    ]
    matched: dict[int, int] = {}

    def assign(row_index: int, visited: set[int]) -> bool:
        for expected_index in edges[row_index]:
            if expected_index in visited:
                continue
            visited.add(expected_index)
            if expected_index not in matched or assign(matched[expected_index], visited):
                matched[expected_index] = row_index
                return True
        return False

    return all(assign(index, set()) for index in range(len(predicted)))


def results_match(
    pred: QueryResult, gold: QueryResult, *, order_matters: bool = False, rel_tol: float = 1e-6
) -> bool:
    """Execution match: do the two results contain the same data?

    - Column names are ignored.
    - Column order is ignored: pred matches if SOME permutation of its columns makes it equal
      to gold. Different column counts never match.
    - Rows are compared as a multiset (duplicates count), or as a sequence if order_matters.
    - Numbers (int / float / Decimal) are equal within rel_tol; None only equals None;
      everything else compares with ==.
    """
    width = len(pred.columns)
    if width != len(gold.columns) or len(pred.rows) != len(gold.rows):
        return False
    if any(len(row) != width for row in (*pred.rows, *gold.rows)):
        return False

    for permutation in itertools.permutations(range(width)):
        reordered = tuple(tuple(row[index] for index in permutation) for row in pred.rows)
        if order_matters:
            if all(_rows_equal(a, b, rel_tol) for a, b in zip(reordered, gold.rows)):
                return True
        elif _multiset_matches(reordered, gold.rows, rel_tol):
            return True
    return False


def percentile(values: Sequence[float], p: float) -> float:
    """p-th percentile (0 <= p <= 100) with linear interpolation between closest ranks
    (the same definition as numpy.percentile's default).

    Raises: ValueError for an empty sequence or p outside [0, 100].
    """
    if not values:
        raise ValueError("percentile is undefined for an empty sequence")
    if not 0 <= p <= 100:
        raise ValueError("percentile p must be between 0 and 100")
    ordered = sorted(float(value) for value in values)
    rank = (len(ordered) - 1) * p / 100
    low = math.floor(rank)
    high = math.ceil(rank)
    if low == high:
        return ordered[low]
    fraction = rank - low
    return ordered[low] + (ordered[high] - ordered[low]) * fraction


@dataclass(frozen=True)
class RunRecord:
    """Outcome of one eval case under one configuration."""

    case_id: str
    fast_correct: bool  # was the first answer shown correct?
    final_correct: bool  # was the answer the user ended with correct?
    corrected: bool  # did a correction event happen?
    time_to_first_ms: float
    time_to_final_ms: float


@dataclass(frozen=True)
class Summary:
    n: int
    fast_accuracy: float
    final_accuracy: float
    corrections: int
    fixed: int  # corrections that turned a wrong answer right
    broke: int  # corrections that turned a right answer wrong
    p50_first_ms: float
    p95_first_ms: float
    p50_final_ms: float
    p95_final_ms: float


def summarize(records: Sequence[RunRecord]) -> Summary:
    """Aggregate records; accuracies are fractions in [0, 1]. Raises ValueError if empty."""
    if not records:
        raise ValueError("cannot summarize an empty sequence")
    count = len(records)
    return Summary(
        n=count,
        fast_accuracy=sum(record.fast_correct for record in records) / count,
        final_accuracy=sum(record.final_correct for record in records) / count,
        corrections=sum(record.corrected for record in records),
        fixed=sum(record.corrected and not record.fast_correct and record.final_correct
                  for record in records),
        broke=sum(record.corrected and record.fast_correct and not record.final_correct
                  for record in records),
        p50_first_ms=percentile([record.time_to_first_ms for record in records], 50),
        p95_first_ms=percentile([record.time_to_first_ms for record in records], 95),
        p50_final_ms=percentile([record.time_to_final_ms for record in records], 50),
        p95_final_ms=percentile([record.time_to_final_ms for record in records], 95),
    )
