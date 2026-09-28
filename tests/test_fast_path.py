from __future__ import annotations

import asyncio
import json

import pytest

from dpa.fast_path import (
    ProposalError,
    parse_semantic_query,
    propose_query,
    propose_sql,
    render_answer,
    run_fast_path,
)
from dpa.llm import FakeLLM, Rule
from dpa.types import Filter, QueryResult, SemanticQuery, Sort

Q = "What is total sales by country?"
GOOD = {"dimensions": ["users.country"], "measures": ["order_items.total_sale_price"],
        "sorts": [{"field": "order_items.total_sale_price", "descending": True}]}


def fake(reply) -> FakeLLM:
    return FakeLLM([Rule(reply if isinstance(reply, str) else json.dumps(reply))])


# --- parse --------------------------------------------------------------------------------


def test_parse_full_payload():
    q = parse_semantic_query(
        {"dimensions": ["users.country"], "measures": ["orders.count"],
         "filters": [{"field": "orders.status", "op": "in", "value": ["Complete"]}],
         "sorts": [{"field": "orders.count", "descending": True}], "limit": 5},
        "order_items",
    )
    assert q == SemanticQuery(
        "order_items", ("users.country",), ("orders.count",),
        (Filter("orders.status", "in", ["Complete"]),), (Sort("orders.count", True),), 5,
    )


def test_parse_empty_payload_uses_defaults():
    assert parse_semantic_query({}, "e") == SemanticQuery("e")


@pytest.mark.parametrize("payload", [
    {"measures": "orders.count"},
    {"filters": [{"field": "orders.status", "op": "~~", "value": 1}]},
    {"limit": "ten"},
])
def test_parse_rejects_bad_shape(payload):
    with pytest.raises(ProposalError):
        parse_semantic_query(payload, "e")


# --- propose ------------------------------------------------------------------------------


def test_propose_query_one_json_call_with_layer_in_prompt(layer):
    llm = fake(GOOD)
    q = asyncio.run(propose_query(Q, layer, "order_items", llm, model="flash"))
    assert q.measures == ("order_items.total_sale_price",)
    assert len(llm.calls) == 1
    call = llm.calls[0]
    assert call.model == "flash" and call.json_mode
    assert Q in call.prompt and "users.country" in call.prompt


@pytest.mark.parametrize("reply", ["not json", {"measures": ["users.salary"]}])
def test_propose_query_rejects(layer, reply):
    with pytest.raises(ProposalError):
        asyncio.run(propose_query(Q, layer, "order_items", fake(reply), model="flash"))


# --- render -------------------------------------------------------------------------------


def test_render_no_rows():
    assert "No results" in render_answer(Q, SemanticQuery("e"), QueryResult(("a",), ()))


def test_render_single_value_rounded():
    text = render_answer(Q, SemanticQuery("e"), QueryResult(("avg",), ((19.16666,),)))
    assert "19.17" in text


def test_render_many_rows_mentions_first_row_and_count():
    r = QueryResult(("country", "total"), (("US", 95.0), ("CN", 20.0)))
    text = render_answer(Q, SemanticQuery("e"), r)
    assert "US" in text and "95" in text and "2" in text


# --- end to end with the fake -------------------------------------------------------------


def test_run_fast_path(conn, layer):
    res = asyncio.run(run_fast_path(Q, layer=layer, explore="order_items", conn=conn,
                                    llm=fake(GOOD), model="flash"))
    assert res.result.rows == (("US", 95.0), ("CN", 20.0))
    assert "US" in res.answer_text
    assert res.sql and res.latency_ms > 0


# --- direct-SQL baseline ------------------------------------------------------------------


@pytest.mark.parametrize("reply", [
    "SELECT 1", "```sql\nSELECT 1;\n```", "  SELECT 1;  \n",
])
def test_propose_sql_strips_fences(reply):
    llm = fake(reply)
    sql = asyncio.run(propose_sql(Q, "CREATE TABLE t (x INT);", llm, model="flash"))
    assert sql == "SELECT 1"
    assert not llm.calls[0].json_mode and "CREATE TABLE t" in llm.calls[0].prompt
