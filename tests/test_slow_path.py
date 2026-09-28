from __future__ import annotations

import asyncio
import json

import pytest

from dpa.llm import FakeLLM, Rule
from dpa.slow_path import MAX_ROWS_SHOWN, audit
from dpa.types import FastResult, QueryResult, SemanticQuery

WRONG = SemanticQuery("order_items", ("users.country",), ("order_items.total_sale_price",))


def fast_result(rows=(("US", 95.0), ("CN", 20.0))) -> FastResult:
    return FastResult(
        question="Total sales of completed orders by country?",
        query=WRONG,
        sql="SELECT /* compiled */ 1",
        result=QueryResult(("users__country", "order_items__total_sale_price"), rows),
        answer_text="US leads with 95.00.",
        latency_ms=10,
    )


def run_audit(layer, reply, rows=None):
    llm = FakeLLM([Rule(reply if isinstance(reply, str) else json.dumps(reply))])
    fr = fast_result() if rows is None else fast_result(rows)
    v = asyncio.run(audit(fr, layer=layer, explore="order_items", llm=llm, model="pro"))
    return v, llm


def test_prompt_contents_and_single_json_call(layer):
    v, llm = run_audit(layer, {"ok": True, "issues": [], "corrected_query": None})
    assert v.status == "pass"
    (call,) = llm.calls
    assert call.model == "pro" and call.json_mode
    for needle in ("completed orders", "users.country", "SELECT /* compiled */", "95"):
        assert needle in call.prompt


def test_only_first_rows_are_shown(layer):
    rows = tuple((f"C{i:03d}", float(i)) for i in range(MAX_ROWS_SHOWN + 5))
    _, llm = run_audit(layer, {"ok": True}, rows=rows)
    assert f"C{MAX_ROWS_SHOWN - 1:03d}" in llm.calls[0].prompt
    assert f"C{MAX_ROWS_SHOWN:03d}" not in llm.calls[0].prompt


def test_fail_with_valid_correction(layer):
    reply = {
        "ok": False,
        "issues": [{"kind": "missing_filter", "detail": "question asks for completed orders"}],
        "corrected_query": {"dimensions": ["users.country"],
                            "measures": ["order_items.total_sale_price"],
                            "filters": [{"field": "orders.status", "op": "=",
                                         "value": "Complete"}]},
    }
    v, _ = run_audit(layer, reply)
    assert v.status == "fail"
    assert v.issues[0].kind == "missing_filter"
    assert v.corrected_query is not None and v.corrected_query.filters[0].value == "Complete"
    assert v.corrected_query.explore == "order_items"


def test_unknown_issue_kind_becomes_other(layer):
    v, _ = run_audit(layer, {"ok": False, "issues": [{"kind": "vibes", "detail": "x"}]})
    assert v.status == "fail" and v.issues[0].kind == "other"


def test_invalid_correction_is_dropped_but_still_fail(layer):
    v, _ = run_audit(layer, {"ok": False, "issues": [{"kind": "wrong_field", "detail": "x"}],
                             "corrected_query": {"measures": ["users.salary"]}})
    assert v.status == "fail" and v.corrected_query is None


@pytest.mark.parametrize("reply", ["not json", {"issues": []}, {"ok": "maybe"}])
def test_bad_reply_is_error_not_exception(layer, reply):
    v, _ = run_audit(layer, reply)
    assert v.status == "error" and v.error


def test_llm_exception_is_error_not_exception(layer):
    llm = FakeLLM([])  # every call raises NoMatchingRule
    v = asyncio.run(audit(fast_result(), layer=layer, explore="order_items", llm=llm, model="pro"))
    assert v.status == "error"
