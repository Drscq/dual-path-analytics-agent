"""Eval cases: natural-language questions with a gold SQL answer.

Tests: tests/test_cases.py.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class EvalCase:
    id: str
    question: str
    gold_sql: str
    order_matters: bool = False
    tags: tuple[str, ...] = ()


def _case_from_payload(payload: Any, line_number: int) -> EvalCase:
    if not isinstance(payload, dict):
        raise TypeError(f"line {line_number}: each case must be a JSON object")
    missing = [key for key in ("id", "question", "gold_sql") if key not in payload]
    if missing:
        raise ValueError(f"line {line_number}: missing required key(s): {', '.join(missing)}")
    case_id = payload["id"]
    question = payload["question"]
    gold_sql = payload["gold_sql"]
    if not all(isinstance(value, str) for value in (case_id, question, gold_sql)):
        raise ValueError(f"line {line_number}: id, question, and gold_sql must be strings")
    order_matters = payload.get("order_matters", False)
    if not isinstance(order_matters, bool):
        raise TypeError(f"line {line_number}: order_matters must be a boolean")
    tags = payload.get("tags", [])
    if not isinstance(tags, list) or any(not isinstance(tag, str) for tag in tags):
        raise ValueError(f"line {line_number}: tags must be a list of strings")
    return EvalCase(case_id, question, gold_sql, order_matters, tuple(tags))


def load_cases(path: str | Path) -> list[EvalCase]:
    """Read a JSONL file, one case per line; blank lines are skipped.

    Required keys: id, question, gold_sql. Optional: order_matters (default false),
    tags (list, default []). Output keeps file order.
    Raises: ValueError naming the line number on a missing required key or bad JSON,
            and naming the id on a duplicate id.
    """
    cases: list[EvalCase] = []
    seen_ids: set[str] = set()
    with Path(path).open(encoding="utf-8") as source:
        for line_number, line in enumerate(source, start=1):
            if not line.strip():
                continue
            try:
                payload = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(f"line {line_number}: invalid JSON: {exc.msg}") from exc
            case = _case_from_payload(payload, line_number)
            if case.id in seen_ids:
                raise ValueError(f"duplicate id {case.id!r}")
            seen_ids.add(case.id)
            cases.append(case)
    return cases
