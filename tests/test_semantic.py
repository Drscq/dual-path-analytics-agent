from __future__ import annotations

import dataclasses
import math

import pytest

from dpa import db
from dpa.semantic import (
    SemanticError,
    UnknownExploreError,
    UnknownFieldError,
    compile_query,
    describe_layer,
    load_semantic_layer,
    resolve_field,
    validate_layer,
)
from dpa.types import Dimension, Explore, Filter, Join, Measure, SemanticQuery, Sort, View

from .conftest import FIXTURES

# --- load / validate / resolve ------------------------------------------------------------


def test_load_matches_python_fixture(layer):
    assert load_semantic_layer(FIXTURES / "layer.yaml") == layer


def test_load_missing_required_key(tmp_path):
    p = tmp_path / "bad.yaml"
    p.write_text("views:\n  - name: v\n    dimensions: []\nexplores: []\n")  # no table
    with pytest.raises(SemanticError):
        load_semantic_layer(p)


def test_valid_layer_has_no_problems(layer):
    assert validate_layer(layer) == []


@pytest.mark.parametrize(
    "mutate",
    [
        pytest.param(lambda L: dataclasses.replace(L, views=L.views + (L.views[0],)),
                     id="duplicate view"),
        pytest.param(lambda L: dataclasses.replace(
            L, explores=L.explores + (Explore("x", "nope"),)), id="unknown base view"),
        pytest.param(lambda L: dataclasses.replace(
            L, explores=(Explore("x", "users", (Join("ghost", "1=1"),)),)), id="unknown join"),
        pytest.param(lambda L: dataclasses.replace(
            L, views=L.views + (View("v", "t", (Dimension("id", "id", "number", True),),
                                     (Measure("s", "sum"),)),)), id="sum without sql"),
        pytest.param(lambda L: dataclasses.replace(
            L, views=L.views + (View("v", "t", (Dimension("a", "a"),)),)), id="no primary key"),
        pytest.param(lambda L: dataclasses.replace(
            L, views=L.views + (View("v", "t", (Dimension("id", "id", "number", True),
                                               Dimension("id", "id2"))),)),
            id="duplicate field"),
    ],
)
def test_validate_catches(layer, mutate):
    assert validate_layer(mutate(layer)) != []


def test_resolve_field(layer):
    f = resolve_field(layer, "order_items.total_sale_price")
    assert isinstance(f, Measure) and f.type == "sum"
    assert isinstance(resolve_field(layer, "users.country"), Dimension)


@pytest.mark.parametrize("name", ["users.nope", "ghost.id", "country", ""])
def test_resolve_unknown(layer, name):
    with pytest.raises(UnknownFieldError):
        resolve_field(layer, name)


# --- describe -----------------------------------------------------------------------------


def test_describe_lists_reachable_fields_only(layer):
    text = describe_layer(layer, "order_items")
    for name in ("order_items.total_sale_price", "orders.status", "users.country"):
        assert name in text
    assert "measure" in text.lower() and "dimension" in text.lower()

    only_users = describe_layer(layer, "users")
    assert "users.country" in only_users
    assert "order_items." not in only_users and "orders." not in only_users


def test_describe_unknown_explore(layer):
    with pytest.raises(UnknownExploreError):
        describe_layer(layer, "nope")


# --- compile (checked by executing the SQL) -----------------------------------------------


def run(conn, layer, **kw):
    q = SemanticQuery(explore=kw.pop("explore", "order_items"), **kw)
    return db.execute(conn, compile_query(q, layer))


def as_set(result):
    return set(result.rows)


def test_group_by_through_intermediate_join(conn, layer):
    r = run(conn, layer, dimensions=("users.country",), measures=("order_items.total_sale_price",))
    assert as_set(r) == {("US", 95.0), ("CN", 20.0)}
    assert r.columns == ("users__country", "order_items__total_sale_price")


def test_count_is_fanout_safe(conn, layer):
    r = run(conn, layer, dimensions=("users.country",), measures=("orders.count",))
    assert as_set(r) == {("US", 3), ("CN", 1)}


def test_measure_only_query(conn, layer):
    r = run(conn, layer, measures=("order_items.count", "order_items.average_sale_price"))
    assert len(r.rows) == 1
    count, avg = r.rows[0]
    assert count == 6 and math.isclose(avg, 115.0 / 6)


def test_dimension_only_query_is_distinct_values(conn, layer):
    r = run(conn, layer, explore="users", dimensions=("users.country",))
    assert sorted(r.rows) == [("CN",), ("US",)]


def test_filter_equals(conn, layer):
    r = run(conn, layer, measures=("order_items.total_sale_price",),
            filters=(Filter("orders.status", "=", "Complete"),))
    assert r.rows == ((110.0,),)


@pytest.mark.parametrize(
    "flt, expected",
    [
        (Filter("orders.status", "in", ["Cancelled"]), 5.0),
        (Filter("orders.created_date", "between", ["2024-02-01", "2024-02-28"]), 45.0),
        (Filter("users.country", "like", "C%"), 20.0),
        (Filter("orders.status", "!=", "Complete"), 5.0),
    ],
)
def test_filter_ops(conn, layer, flt, expected):
    r = run(conn, layer, measures=("order_items.total_sale_price",), filters=(flt,))
    assert r.rows == ((expected,),)


def test_filter_value_is_escaped(conn, layer):
    r = run(conn, layer, measures=("orders.count",),
            filters=(Filter("orders.status", "=", "O'Brien'); DROP TABLE users; --"),))
    assert r.rows == ((0,),)
    assert db.execute(conn, "SELECT count(*) FROM users").rows == ((3,),)


def test_sort_and_limit(conn, layer):
    r = run(conn, layer, dimensions=("users.country",), measures=("order_items.total_sale_price",),
            sorts=(Sort("order_items.total_sale_price", descending=True),), limit=1)
    assert r.rows == (("US", 95.0),)


@pytest.mark.parametrize(
    "kw, err",
    [
        ({"explore": "nope", "measures": ("users.count",)}, UnknownExploreError),
        ({"measures": ("users.nope",)}, UnknownFieldError),
        ({"explore": "users", "measures": ("order_items.count",)}, UnknownFieldError),
        ({}, SemanticError),
        ({"measures": ("orders.count",),
          "filters": (Filter("order_items.total_sale_price", ">", 1),)}, SemanticError),
    ],
    ids=["unknown explore", "unknown field", "unreachable view", "no fields", "filter on measure"],
)
def test_compile_rejects(layer, kw, err):
    q = SemanticQuery(explore=kw.pop("explore", "order_items"), **kw)
    with pytest.raises(err):
        compile_query(q, layer)
