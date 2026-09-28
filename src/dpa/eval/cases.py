"""Eval cases: natural-language questions with a gold SQL answer.

TODO(Changqi): implement load_cases. Tests: tests/test_cases.py.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class EvalCase:
    id: str
    question: str
    gold_sql: str
    order_matters: bool = False
    tags: tuple[str, ...] = ()


def load_cases(path: str | Path) -> list[EvalCase]:
    """Read a JSONL file, one case per line; blank lines are skipped.

    Required keys: id, question, gold_sql. Optional: order_matters (default false),
    tags (list, default []). Output keeps file order.
    Raises: ValueError naming the line number on a missing required key or bad JSON,
            and naming the id on a duplicate id.
    """
    raise NotImplementedError
