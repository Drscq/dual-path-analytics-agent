from __future__ import annotations

import pytest

from dpa.eval.cases import EvalCase, load_cases


def write(tmp_path, text):
    p = tmp_path / "cases.jsonl"
    p.write_text(text)
    return p


def test_load_cases_defaults_and_order(tmp_path):
    p = write(tmp_path,
              '{"id": "a", "question": "q1", "gold_sql": "SELECT 1"}\n'
              "\n"
              '{"id": "b", "question": "q2", "gold_sql": "SELECT 2", "order_matters": true,'
              ' "tags": ["top_k"]}\n')
    assert load_cases(p) == [
        EvalCase("a", "q1", "SELECT 1"),
        EvalCase("b", "q2", "SELECT 2", True, ("top_k",)),
    ]


def test_missing_key_names_line(tmp_path):
    p = write(tmp_path, '{"id": "a", "question": "q", "gold_sql": "x"}\n{"id": "b"}\n')
    with pytest.raises(ValueError, match="2"):
        load_cases(p)


def test_bad_json_names_line(tmp_path):
    with pytest.raises(ValueError, match="1"):
        load_cases(write(tmp_path, "{not json\n"))


def test_duplicate_id(tmp_path):
    line = '{"id": "dup", "question": "q", "gold_sql": "x"}\n'
    with pytest.raises(ValueError, match="dup"):
        load_cases(write(tmp_path, line * 2))
