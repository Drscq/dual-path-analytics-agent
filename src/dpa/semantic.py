"""Semantic layer: load it, check it, describe it to a model, compile queries against it.

TODO(Changqi): every function here is yours to implement. Tests: tests/test_semantic.py.

YAML format (a small subset of LookML's ideas; see semantic/thelook.yaml):

    views:
      - name: orders
        table: orders
        dimensions:
          - {name: order_id, sql: "${TABLE}.order_id", type: number, primary_key: true}
          - {name: status,   sql: "${TABLE}.status",   type: string}
        measures:
          - {name: count, type: count}
          - {name: total_sale_price, type: sum, sql: "${TABLE}.sale_price"}
    explores:
      - name: order_items
        base_view: order_items
        joins:
          - {view: orders, sql_on: "${order_items.order_id} = ${orders.order_id}",
             relationship: many_to_one}

Field names are always qualified as "view.field".
"""

from __future__ import annotations

from pathlib import Path

from dpa.types import Dimension, Measure, SemanticLayer, SemanticQuery


class SemanticError(ValueError):
    """Base class for every semantic-layer / semantic-query error."""


class UnknownExploreError(SemanticError):
    pass


class UnknownFieldError(SemanticError):
    pass


def load_semantic_layer(path: str | Path) -> SemanticLayer:
    """Parse the YAML file at `path` into a SemanticLayer.

    Input:  path to a YAML file in the format above.
    Output: SemanticLayer with views and explores in file order; missing optional keys take
            the dataclass defaults (e.g. dimension type "string", joins ()).
    Raises: SemanticError if a required key (name / table / sql_on / ...) is missing.
    """
    raise NotImplementedError


def validate_layer(layer: SemanticLayer) -> list[str]:
    """Return a list of human-readable problems; [] means the layer is usable.

    Must detect at least:
      - two views with the same name, or two fields with the same name inside one view
      - an explore whose base_view or joined view does not exist
      - a measure of any type other than "count" with no sql
      - a view with no primary_key dimension (count measures need one, see compile_query)
    """
    raise NotImplementedError


def resolve_field(layer: SemanticLayer, qualified_name: str) -> Dimension | Measure:
    """Look up "view.field".

    Raises: UnknownFieldError if the view or field does not exist, or the name is not
            of the form "view.field".
    """
    raise NotImplementedError


def describe_layer(layer: SemanticLayer, explore: str) -> str:
    """Plain-text description of one explore for a model prompt.

    Output must mention every field reachable in the explore as "view.field" together with
    its kind (dimension / measure) and type, and its description if any. Fields of views
    not reachable from the explore must NOT appear.
    Raises: UnknownExploreError.
    """
    raise NotImplementedError


def compile_query(query: SemanticQuery, layer: SemanticLayer) -> str:
    """Compile a SemanticQuery into one DuckDB SQL statement.

    Semantics (these are what the tests check, by executing the SQL):
      - FROM the explore's base_view; LEFT JOIN only the joined views that the query uses
        (in any role: dimension, measure, filter, sort) plus any views needed to reach them
        through the join graph.
      - SELECT dimensions first, then measures, in the order given; each output column is
        aliased "view__field" (double underscore).
      - GROUP BY every dimension when there is at least one measure.
      - Fan-out safety: a measure of type "count" is COUNT(DISTINCT <primary key of its view>),
        so joining a one-to-many view never inflates it.
      - filters become WHERE clauses on dimensions (ANDed); "in" takes a list, "between" a
        pair, "like" a SQL pattern. String values must be escaped, not interpolated raw.
      - sorts become ORDER BY; limit becomes LIMIT.
    Raises: UnknownExploreError, UnknownFieldError (including a field whose view is not
            reachable from the explore), SemanticError for a query with no fields at all
            or a filter on a measure.
    """
    raise NotImplementedError
