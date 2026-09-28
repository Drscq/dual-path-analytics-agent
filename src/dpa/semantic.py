"""Semantic layer: load it, check it, describe it to a model, compile queries against it.

Tests: tests/test_semantic.py.

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

import math
import re
from decimal import Decimal
from pathlib import Path
from typing import Any

import yaml

from dpa.types import Dimension, Explore, Join, Measure, SemanticLayer, SemanticQuery, View


class SemanticError(ValueError):
    """Base class for every semantic-layer / semantic-query error."""


class UnknownExploreError(SemanticError):
    pass


class UnknownFieldError(SemanticError):
    pass


_MACRO = re.compile(r"\$\{([^}]+)\}")
_FIELD_REFERENCE = re.compile(r"\$\{([^}.]+)\.[^}]+\}")
_FILTER_OPS = {"=", "!=", ">", ">=", "<", "<=", "in", "between", "like"}


def _require(mapping: dict, key: str, context: str) -> Any:
    if key not in mapping:
        raise SemanticError(f"{context} is missing required key {key!r}")
    return mapping[key]


def _mapping(value: Any, context: str) -> dict:
    if not isinstance(value, dict):
        raise SemanticError(f"{context} must be a mapping")
    return value


def _sequence(value: Any, context: str) -> list:
    if not isinstance(value, list):
        raise SemanticError(f"{context} must be a list")
    return value


def load_semantic_layer(path: str | Path) -> SemanticLayer:
    """Parse the YAML file at `path` into a SemanticLayer.

    Input:  path to a YAML file in the format above.
    Output: SemanticLayer with views and explores in file order; missing optional keys take
            the dataclass defaults (e.g. dimension type "string", joins ()).
    Raises: SemanticError if a required key (name / table / sql_on / ...) is missing.
    """
    try:
        raw = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise SemanticError(f"invalid semantic YAML: {exc}") from exc

    data = _mapping(raw, "semantic layer")
    raw_views = _sequence(_require(data, "views", "semantic layer"), "views")
    raw_explores = _sequence(_require(data, "explores", "semantic layer"), "explores")
    views: list[View] = []
    explores: list[Explore] = []

    for index, item in enumerate(raw_views):
        context = f"view at index {index}"
        spec = _mapping(item, context)
        name = _require(spec, "name", context)
        table = _require(spec, "table", context)
        dimensions = []
        for dim_index, dim_item in enumerate(
            _sequence(_require(spec, "dimensions", context), f"{context}.dimensions")
        ):
            dim_context = f"{context}.dimensions[{dim_index}]"
            dim = _mapping(dim_item, dim_context)
            dimensions.append(
                Dimension(
                    name=_require(dim, "name", dim_context),
                    sql=_require(dim, "sql", dim_context),
                    type=dim.get("type", "string"),
                    primary_key=dim.get("primary_key", False),
                    description=dim.get("description", ""),
                )
            )

        measures = []
        for measure_index, measure_item in enumerate(spec.get("measures", [])):
            measure_context = f"{context}.measures[{measure_index}]"
            measure = _mapping(measure_item, measure_context)
            measures.append(
                Measure(
                    name=_require(measure, "name", measure_context),
                    type=_require(measure, "type", measure_context),
                    sql=measure.get("sql"),
                    description=measure.get("description", ""),
                )
            )
        views.append(View(name, table, tuple(dimensions), tuple(measures)))

    for index, item in enumerate(raw_explores):
        context = f"explore at index {index}"
        spec = _mapping(item, context)
        joins = []
        for join_index, join_item in enumerate(spec.get("joins", [])):
            join_context = f"{context}.joins[{join_index}]"
            join = _mapping(join_item, join_context)
            joins.append(
                Join(
                    view=_require(join, "view", join_context),
                    sql_on=_require(join, "sql_on", join_context),
                    relationship=join.get("relationship", "many_to_one"),
                )
            )
        explores.append(
            Explore(
                name=_require(spec, "name", context),
                base_view=_require(spec, "base_view", context),
                joins=tuple(joins),
                description=spec.get("description", ""),
            )
        )

    return SemanticLayer(tuple(views), tuple(explores))


def validate_layer(layer: SemanticLayer) -> list[str]:
    """Return a list of human-readable problems; [] means the layer is usable.

    Must detect at least:
      - two views with the same name, or two fields with the same name inside one view
      - an explore whose base_view or joined view does not exist
      - a measure of any type other than "count" with no sql
      - a view with no primary_key dimension (count measures need one, see compile_query)
    """
    problems: list[str] = []
    view_names = {view.name for view in layer.views}
    seen_views: set[str] = set()
    for view in layer.views:
        if view.name in seen_views:
            problems.append(f"duplicate view name {view.name!r}")
        seen_views.add(view.name)

        seen_fields: set[str] = set()
        for field in (*view.dimensions, *view.measures):
            if field.name in seen_fields:
                problems.append(f"duplicate field {view.name}.{field.name}")
            seen_fields.add(field.name)
        if not any(dimension.primary_key for dimension in view.dimensions):
            problems.append(f"view {view.name!r} has no primary_key dimension")
        for measure in view.measures:
            if measure.type != "count" and not measure.sql:
                problems.append(f"measure {view.name}.{measure.name} has no sql")

    for explore in layer.explores:
        if explore.base_view not in view_names:
            problems.append(
                f"explore {explore.name!r} has unknown base view {explore.base_view!r}"
            )
        for join in explore.joins:
            if join.view not in view_names:
                problems.append(f"explore {explore.name!r} has unknown joined view {join.view!r}")
    return problems


def _view_map(layer: SemanticLayer) -> dict[str, View]:
    return {view.name: view for view in layer.views}


def _explore_map(layer: SemanticLayer) -> dict[str, Explore]:
    return {explore.name: explore for explore in layer.explores}


def resolve_field(layer: SemanticLayer, qualified_name: str) -> Dimension | Measure:
    """Look up "view.field".

    Raises: UnknownFieldError if the view or field does not exist, or the name is not
            of the form "view.field".
    """
    if not isinstance(qualified_name, str):
        raise UnknownFieldError(f"invalid qualified field name {qualified_name!r}")
    parts = qualified_name.split(".")
    if len(parts) != 2 or not all(parts):
        raise UnknownFieldError(f"invalid qualified field name {qualified_name!r}")
    view_name, field_name = parts
    view = _view_map(layer).get(view_name)
    if view is None:
        raise UnknownFieldError(f"unknown view {view_name!r} in field {qualified_name!r}")
    for field in (*view.dimensions, *view.measures):
        if field.name == field_name:
            return field
    raise UnknownFieldError(f"unknown field {qualified_name!r}")


def _join_dependencies(join: Join, base_view: str) -> set[str]:
    references = {match.group(1) for match in _FIELD_REFERENCE.finditer(join.sql_on)}
    references.discard(join.view)
    return references or {base_view}


def _reachable_joins(explore: Explore) -> tuple[set[str], list[Join]]:
    reachable = {explore.base_view}
    pending: list[Join] = []
    seen_targets = {explore.base_view}
    for join in explore.joins:
        if join.view not in seen_targets:
            pending.append(join)
            seen_targets.add(join.view)

    ordered: list[Join] = []
    while pending:
        ready = next(
            (
                join
                for join in pending
                if _join_dependencies(join, explore.base_view) <= reachable
            ),
            None,
        )
        if ready is None:
            break
        pending.remove(ready)
        reachable.add(ready.view)
        ordered.append(ready)
    return reachable, ordered


def describe_layer(layer: SemanticLayer, explore: str) -> str:
    """Plain-text description of one explore for a model prompt.

    Output must mention every field reachable in the explore as "view.field" together with
    its kind (dimension / measure) and type, and its description if any. Fields of views
    not reachable from the explore must NOT appear.
    Raises: UnknownExploreError.
    """
    spec = _explore_map(layer).get(explore)
    if spec is None:
        raise UnknownExploreError(f"unknown explore {explore!r}")
    reachable, _ = _reachable_joins(spec)
    views = _view_map(layer)
    lines = [f"Explore: {spec.name}", f"Base view: {spec.base_view}"]
    if spec.description:
        lines.append(f"Description: {spec.description}")

    for view_name in (view.name for view in layer.views if view.name in reachable):
        view = views[view_name]
        lines.append(f"\nView: {view.name}")
        for dimension in view.dimensions:
            line = f"- {view.name}.{dimension.name} (dimension, type: {dimension.type})"
            if dimension.description:
                line += f" — {dimension.description}"
            lines.append(line)
        for measure in view.measures:
            line = f"- {view.name}.{measure.name} (measure, type: {measure.type})"
            if measure.description:
                line += f" — {measure.description}"
            lines.append(line)
    return "\n".join(lines)


def _quote_identifier(identifier: str) -> str:
    return '"' + identifier.replace('"', '""') + '"'


def _table_reference(table: str) -> str:
    return ".".join(_quote_identifier(part) for part in table.split("."))


def _expand_sql(
    layer: SemanticLayer, sql: str, default_view: str, stack: tuple[str, ...] = ()
) -> str:
    def replace(match: re.Match) -> str:
        reference = match.group(1)
        if reference == "TABLE":
            return _quote_identifier(default_view)
        if "." not in reference:
            raise SemanticError(f"invalid SQL reference ${{{reference}}}")
        field_name = reference
        if field_name in stack:
            raise SemanticError(f"cyclic SQL field reference: {field_name}")
        field = resolve_field(layer, field_name)
        if not isinstance(field, Dimension):
            raise SemanticError(f"SQL reference {field_name!r} must name a dimension")
        return _expand_sql(layer, field.sql, field_name.split(".", 1)[0], (*stack, field_name))

    return _MACRO.sub(replace, sql)


def _primary_key(layer: SemanticLayer, view_name: str) -> Dimension:
    view = _view_map(layer).get(view_name)
    if view is not None:
        for dimension in view.dimensions:
            if dimension.primary_key:
                return dimension
    raise SemanticError(f"view {view_name!r} has no primary_key dimension")


def _measure_sql(layer: SemanticLayer, qualified_name: str, measure: Measure) -> str:
    view_name = qualified_name.split(".", 1)[0]
    if measure.type == "count":
        key = _primary_key(layer, view_name)
        expression = _expand_sql(layer, key.sql, view_name, (qualified_name,))
        return f"COUNT(DISTINCT {expression})"
    if not measure.sql:
        raise SemanticError(f"measure {qualified_name!r} has no sql")
    expression = _expand_sql(layer, measure.sql, view_name, (qualified_name,))
    if measure.type == "count_distinct":
        return f"COUNT(DISTINCT {expression})"
    aggregates = {"sum": "SUM", "average": "AVG", "min": "MIN", "max": "MAX"}
    aggregate = aggregates.get(measure.type)
    if aggregate is None:
        raise SemanticError(f"unsupported measure type {measure.type!r}")
    return f"{aggregate}({expression})"


def _sql_literal(value: Any) -> str:
    if value is None:
        return "NULL"
    if isinstance(value, bool):
        return "TRUE" if value else "FALSE"
    if isinstance(value, str):
        return "'" + value.replace("'", "''") + "'"
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        if not math.isfinite(value):
            raise SemanticError("filter values must be finite numbers")
        return repr(value)
    if isinstance(value, Decimal):
        if not value.is_finite():
            raise SemanticError("filter values must be finite numbers")
        return str(value)
    raise SemanticError(f"unsupported filter value {value!r}")


def _filter_sql(layer: SemanticLayer, field_name: str, op: str, value: Any) -> str:
    if op not in _FILTER_OPS:
        raise SemanticError(f"unsupported filter operator {op!r}")
    expression = _expand_sql(layer, resolve_field(layer, field_name).sql, field_name.split(".", 1)[0])
    if op == "in":
        if not isinstance(value, (list, tuple)):
            raise SemanticError("an 'in' filter needs a list of values")
        if not value:
            return "FALSE"
        values = ", ".join(_sql_literal(item) for item in value)
        return f"{expression} IN ({values})"
    if op == "between":
        if not isinstance(value, (list, tuple)) or len(value) != 2:
            raise SemanticError("a 'between' filter needs exactly two values")
        return f"{expression} BETWEEN {_sql_literal(value[0])} AND {_sql_literal(value[1])}"
    if value is None and op in ("=", "!="):
        return f"{expression} IS {'NOT ' if op == '!=' else ''}NULL"
    return f"{expression} {op} {_sql_literal(value)}"


def _required_join_order(explore: Explore, required: set[str]) -> list[Join]:
    reachable, ordered = _reachable_joins(explore)
    unreachable = required - reachable
    if unreachable:
        name = min(unreachable)
        raise UnknownFieldError(f"view {name!r} is not reachable from explore {explore.name!r}")

    needed = set(required)
    changed = True
    while changed:
        changed = False
        for join in ordered:
            if join.view in needed:
                before = len(needed)
                needed.update(_join_dependencies(join, explore.base_view))
                changed |= len(needed) != before
    return [join for join in ordered if join.view in needed]


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
    explore = _explore_map(layer).get(query.explore)
    if explore is None:
        raise UnknownExploreError(f"unknown explore {query.explore!r}")
    if not query.dimensions and not query.measures:
        raise SemanticError("a semantic query must select at least one field")

    dimensions: list[tuple[str, Dimension]] = []
    measures: list[tuple[str, Measure]] = []
    fields_by_name: dict[str, Dimension | Measure] = {}
    for name in query.dimensions:
        field = resolve_field(layer, name)
        if not isinstance(field, Dimension):
            raise SemanticError(f"selected field {name!r} is not a dimension")
        dimensions.append((name, field))
        fields_by_name[name] = field
    for name in query.measures:
        field = resolve_field(layer, name)
        if not isinstance(field, Measure):
            raise SemanticError(f"selected field {name!r} is not a measure")
        measures.append((name, field))
        fields_by_name[name] = field

    for filter_spec in query.filters:
        field = resolve_field(layer, filter_spec.field)
        if not isinstance(field, Dimension):
            raise SemanticError(f"filter field {filter_spec.field!r} is a measure")
        fields_by_name[filter_spec.field] = field
    for sort in query.sorts:
        fields_by_name[sort.field] = resolve_field(layer, sort.field)

    required_views = {name.split(".", 1)[0] for name in fields_by_name}
    joins = _required_join_order(explore, required_views)
    views = _view_map(layer)

    select_parts: list[str] = []
    for name, dimension in dimensions:
        expression = _expand_sql(layer, dimension.sql, name.split(".", 1)[0])
        select_parts.append(f"{expression} AS {_quote_identifier(name.replace('.', '__'))}")
    for name, measure in measures:
        expression = _measure_sql(layer, name, measure)
        select_parts.append(f"{expression} AS {_quote_identifier(name.replace('.', '__'))}")

    base = views.get(explore.base_view)
    if base is None:
        raise UnknownExploreError(
            f"explore {explore.name!r} has unknown base view {explore.base_view!r}"
        )
    from_clause = f"FROM {_table_reference(base.table)} AS {_quote_identifier(base.name)}"
    for join in joins:
        view = views.get(join.view)
        if view is None:
            raise UnknownFieldError(f"unknown joined view {join.view!r}")
        condition = _expand_sql(layer, join.sql_on, join.view)
        from_clause += (
            f" LEFT JOIN {_table_reference(view.table)} AS {_quote_identifier(view.name)}"
            f" ON {condition}"
        )

    where_parts = [
        _filter_sql(layer, filter_spec.field, filter_spec.op, filter_spec.value)
        for filter_spec in query.filters
    ]
    sql = f"SELECT {'DISTINCT ' if not measures else ''}{', '.join(select_parts)} {from_clause}"
    if where_parts:
        sql += " WHERE " + " AND ".join(where_parts)
    if measures and dimensions:
        group_parts = [
            _expand_sql(layer, dimension.sql, name.split(".", 1)[0])
            for name, dimension in dimensions
        ]
        sql += " GROUP BY " + ", ".join(group_parts)

    if query.sorts:
        selected_names = {name for name, _ in (*dimensions, *measures)}
        order_parts = []
        for sort in query.sorts:
            if sort.field in selected_names:
                expression = _quote_identifier(sort.field.replace(".", "__"))
            else:
                field = fields_by_name[sort.field]
                if isinstance(field, Dimension):
                    expression = _expand_sql(layer, field.sql, sort.field.split(".", 1)[0])
                else:
                    expression = _measure_sql(layer, sort.field, field)
            order_parts.append(f"{expression} {'DESC' if sort.descending else 'ASC'}")
        sql += " ORDER BY " + ", ".join(order_parts)

    if query.limit is not None:
        if isinstance(query.limit, bool) or not isinstance(query.limit, int) or query.limit < 0:
            raise SemanticError("limit must be a non-negative integer or None")
        sql += f" LIMIT {query.limit}"
    return sql
