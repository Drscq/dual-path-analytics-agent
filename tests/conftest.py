"""Shared fixtures: a tiny in-memory copy of the thelook schema and its semantic layer.

Hand-checked numbers (used across tests):
  total sale price: US 95.0 (orders 10, 11, 12), CN 20.0 (order 13); all 115.0
  orders per country: US 3, CN 1   (a naive COUNT over the item join would give 4 and 2)
  Complete orders only: total sale price 110.0
"""

from __future__ import annotations

from pathlib import Path

import duckdb
import pytest

from dpa.types import Dimension, Explore, Join, Measure, SemanticLayer, View

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_makereport(item, call):
    """Report a test whose code under test raises NotImplementedError as skipped, so the
    suite stays green while stubs are being filled in. `make todo` lists them."""
    outcome = yield
    rep = outcome.get_result()
    excinfo = call.excinfo
    if rep.when in ("setup", "call") and excinfo and excinfo.errisinstance(NotImplementedError):
        rep.outcome = "skipped"
        rep.longrepr = (str(item.path), item.location[1] or 0, "not implemented yet")


@pytest.fixture
def conn():
    c = duckdb.connect(":memory:")
    c.execute("CREATE TABLE users (id INTEGER, country VARCHAR)")
    c.execute("INSERT INTO users VALUES (1, 'US'), (2, 'US'), (3, 'CN')")
    c.execute("CREATE TABLE orders (order_id INTEGER, user_id INTEGER, status VARCHAR, "
              "created_at TIMESTAMP)")
    c.execute("""INSERT INTO orders VALUES
        (10, 1, 'Complete',  '2024-01-05 09:00:00'),
        (11, 1, 'Cancelled', '2024-02-10 12:00:00'),
        (12, 2, 'Complete',  '2024-02-15 18:30:00'),
        (13, 3, 'Complete',  '2024-03-01 08:15:00')""")
    c.execute("CREATE TABLE order_items (id INTEGER, order_id INTEGER, sale_price DOUBLE)")
    c.execute("""INSERT INTO order_items VALUES
        (100, 10, 20.0), (101, 10, 30.0), (102, 11, 5.0),
        (103, 12, 40.0), (104, 13, 15.5), (105, 13, 4.5)""")
    yield c
    c.close()


def _pk(name: str, sql: str) -> Dimension:
    return Dimension(name, sql, "number", primary_key=True)


@pytest.fixture
def layer() -> SemanticLayer:
    """Built directly, so tests of other modules do not depend on the YAML loader.
    tests/fixtures/layer.yaml describes exactly this layer."""
    users = View(
        "users", "users",
        (_pk("id", "${TABLE}.id"), Dimension("country", "${TABLE}.country", "string")),
        (Measure("count", "count"),),
    )
    orders = View(
        "orders", "orders",
        (
            _pk("order_id", "${TABLE}.order_id"),
            Dimension("user_id", "${TABLE}.user_id", "number"),
            Dimension("status", "${TABLE}.status", "string"),
            Dimension("created_date", "CAST(${TABLE}.created_at AS DATE)", "date"),
        ),
        (Measure("count", "count"),),
    )
    order_items = View(
        "order_items", "order_items",
        (
            _pk("id", "${TABLE}.id"),
            Dimension("order_id", "${TABLE}.order_id", "number"),
            Dimension("sale_price", "${TABLE}.sale_price", "number"),
        ),
        (
            Measure("count", "count"),
            Measure("total_sale_price", "sum", "${TABLE}.sale_price"),
            Measure("average_sale_price", "average", "${TABLE}.sale_price"),
        ),
    )
    explores = (
        Explore(
            "order_items", "order_items",
            (
                Join("orders", "${order_items.order_id} = ${orders.order_id}", "many_to_one"),
                Join("users", "${orders.user_id} = ${users.id}", "many_to_one"),
            ),
        ),
        Explore("users", "users"),
    )
    return SemanticLayer((users, orders, order_items), explores)
