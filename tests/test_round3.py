"""Round 3: the fast path chooses the explore; the audit sees the population and stored values.

Uses the real semantic layer (no database, no network: FakeLLM).
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest

from dpa.fast_path import ProposalError, propose_query
from dpa.llm import FakeLLM, Rule
from dpa.semantic import compile_query, dimension_values_sql, load_semantic_layer
from dpa.slow_path import audit
from dpa.types import FastResult, Filter, QueryResult, SemanticQuery

LAYER = load_semantic_layer(Path(__file__).parents[1] / "semantic" / "thelook.yaml")
BOTH = ("order_items", "users")
Q = "How many customers are based in Brazil?"


def fake(reply):
    return FakeLLM([Rule(reply if isinstance(reply, str) else json.dumps(reply))])


def test_fast_path_takes_the_chosen_explore_and_shows_both():
    llm = fake({"explore": "users", "measures": ["users.count"],
                "filters": [{"field": "users.country", "op": "=", "value": "Brasil"}]})
    q = asyncio.run(propose_query(Q, LAYER, "order_items", llm, model="flash", explores=BOTH))
    assert q.explore == "users"
    assert "Explore: order_items" in llm.calls[0].prompt and "Explore: users" in llm.calls[0].prompt
    assert compile_query(q, LAYER).startswith('SELECT COUNT(DISTINCT "users".id)')


def test_fast_path_rejects_an_unknown_explore():
    llm = fake({"explore": "customers", "measures": ["users.count"]})
    with pytest.raises(ProposalError):
        asyncio.run(propose_query(Q, LAYER, "order_items", llm, model="flash", explores=BOTH))


def _fast(country="Brazil"):
    query = SemanticQuery("order_items", (), ("users.count",),
                          (Filter("users.country", "=", country),))
    return FastResult(Q, query, compile_query(query, LAYER), QueryResult(("n",), ((0,),)), "0", 5)


def test_audit_adds_population_and_values_and_may_switch_explore():
    reply = {"ok": False, "issues": [{"kind": "wrong_filter", "detail": "stored as Brasil"}],
             "corrected_query": {"explore": "users", "measures": ["users.count"],
                                 "filters": [{"field": "users.country", "op": "=",
                                              "value": "Brasil"}]}}
    llm = fake(reply)
    v = asyncio.run(audit(_fast(), layer=LAYER, explore="order_items", llm=llm, model="pro",
                          explores=BOTH, value_lookup=lambda field: ["Brasil", "China"]))
    prompt = llm.calls[0].prompt
    assert 'base\nview is "order_items"' in prompt and "Explore: users" in prompt
    assert '- users.country: ["Brasil", "China"]' in prompt
    assert v.status == "fail" and v.corrected_query.explore == "users"


def test_audit_without_round3_context_is_unchanged():
    llm = fake({"ok": True})
    asyncio.run(audit(_fast(), layer=LAYER, explore="order_items", llm=llm, model="pro"))
    assert "Population check" not in llm.calls[0].prompt
    assert "Stored values" not in llm.calls[0].prompt


def test_dimension_values_sql_reads_the_views_own_table():
    sql = dimension_values_sql(LAYER, "users.country", 60)
    assert 'FROM "users" AS "users"' in sql and "JOIN" not in sql and sql.endswith("LIMIT 60")
