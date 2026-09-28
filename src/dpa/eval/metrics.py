"""Accuracy and latency metrics.

TODO(Changqi): implement every function. Tests: tests/test_metrics.py.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from dpa.types import QueryResult


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
    raise NotImplementedError


def percentile(values: Sequence[float], p: float) -> float:
    """p-th percentile (0 <= p <= 100) with linear interpolation between closest ranks
    (the same definition as numpy.percentile's default).

    Raises: ValueError for an empty sequence or p outside [0, 100].
    """
    raise NotImplementedError


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
    raise NotImplementedError
