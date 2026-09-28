"""Timing is simulated with FakeLLM delays: fast = 50 ms, slow = 200 ms.
Margins are wide (tens of ms) so the tests are stable on a loaded CI machine."""

from __future__ import annotations

import asyncio
import json

from dpa.llm import FakeLLM, Rule
from dpa.orchestrator import answer

Q = "Total sales of completed orders by country?"
FAST_Q = {"dimensions": ["users.country"], "measures": ["order_items.total_sale_price"],
          "sorts": [{"field": "order_items.total_sale_price", "descending": True}]}
FIXED_Q = {**FAST_Q, "filters": [{"field": "orders.status", "op": "=", "value": "Complete"}]}

PASS = {"ok": True, "issues": [], "corrected_query": None}
FAIL_FIXED = {"ok": False, "issues": [{"kind": "missing_filter", "detail": "completed only"}],
              "corrected_query": FIXED_Q}
FAIL_NO_FIX = {"ok": False, "issues": [{"kind": "wrong_time_window", "detail": "which year?"}],
               "corrected_query": None}


def llm_with(verdict, slow_s=0.2, fast_s=0.05):
    verdict = verdict if isinstance(verdict, str) else json.dumps(verdict)
    return FakeLLM([Rule(json.dumps(FAST_Q), model="flash", delay_s=fast_s),
                    Rule(verdict, model="pro", delay_s=slow_s)])


def go(conn, layer, llm, **kw):
    return asyncio.run(answer(Q, layer=layer, explore="order_items", conn=conn, llm=llm,
                              fast_model="flash", slow_model="pro", **kw))


# --- amend --------------------------------------------------------------------------------


def test_amend_pass_shows_fast_answer_without_waiting_for_audit(conn, layer):
    t = go(conn, layer, llm_with(PASS), mode="amend")
    assert [e.kind for e in t.events] == ["first"]
    assert t.time_to_first_ms < 150  # fast only; the 200 ms audit is not on this path
    assert t.verdict.status == "pass"
    assert t.final_result.rows == t.fast.result.rows


def test_amend_fail_with_correction_emits_correction(conn, layer):
    t = go(conn, layer, llm_with(FAIL_FIXED), mode="amend")
    assert [e.kind for e in t.events] == ["first", "correction"]
    assert t.time_to_first_ms < 150
    assert t.time_to_final_ms >= 240  # 50 fast + 200 audit
    assert set(t.final_result.rows) == {("US", 90.0), ("CN", 20.0)}  # Complete only
    assert t.final_query.filters


def test_amend_fail_without_correction_adds_caveat(conn, layer):
    t = go(conn, layer, llm_with(FAIL_NO_FIX), mode="amend")
    assert [e.kind for e in t.events] == ["first", "caveat"]
    assert "which year" in t.events[1].text
    assert t.final_result.rows == t.fast.result.rows


def test_amend_auditor_error_changes_nothing(conn, layer):
    t = go(conn, layer, llm_with("garbage"), mode="amend")
    assert [e.kind for e in t.events] == ["first"]
    assert t.verdict.status == "error"


# --- hold ---------------------------------------------------------------------------------


def test_hold_verdict_in_time_shows_one_corrected_answer(conn, layer):
    t = go(conn, layer, llm_with(FAIL_FIXED), mode="hold", hold_deadline_ms=500)
    assert [e.kind for e in t.events] == ["first"]
    assert t.time_to_first_ms >= 240
    assert set(t.final_result.rows) == {("US", 90.0), ("CN", 20.0)}
    assert "90" in t.events[0].text


def test_hold_deadline_passes_then_behaves_like_amend(conn, layer):
    t = go(conn, layer, llm_with(FAIL_FIXED), mode="hold", hold_deadline_ms=60)
    assert [e.kind for e in t.events] == ["first", "correction"]
    assert 100 <= t.time_to_first_ms < 200  # 50 fast + 60 deadline
    assert t.time_to_final_ms >= 240


def test_hold_pass_in_time(conn, layer):
    t = go(conn, layer, llm_with(PASS), mode="hold", hold_deadline_ms=500)
    assert [e.kind for e in t.events] == ["first"]
    assert t.time_to_first_ms >= 240
