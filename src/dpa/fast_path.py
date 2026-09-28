"""Fast path: question -> semantic query -> SQL -> result -> answer text, with one cheap model call.

Tests: tests/test_fast_path.py.
"""

from __future__ import annotations

import json
import re
import time
from typing import Any

import duckdb

from dpa import db
from dpa.llm import LLMClient
from dpa.semantic import (
    UnknownFieldError,
    compile_query,
    describe_layer,
    resolve_field,
)
from dpa.types import (
    FastResult,
    Filter,
    QueryResult,
    SemanticLayer,
    SemanticQuery,
    Sort,
)


class ProposalError(ValueError):
    """The model's output could not be turned into a valid query."""


_FILTER_OPERATORS = {"=", "!=", ">", ">=", "<", "<=", "in", "between", "like"}

SEMANTIC_QUERY_FORMAT = """A semantic query is one JSON object with exactly these keys:
  "dimensions": ["view.field", ...]   dimension fields to group by
  "measures":   ["view.field", ...]   measure fields to aggregate
  "filters":    [{"field": "view.field", "op": OP, "value": VALUE}, ...]   dimensions only
  "sorts":      [{"field": "view.field", "descending": true | false}, ...]
  "limit":      an integer, or null
OP is exactly one of: "=", "!=", ">", ">=", "<", "<=", "in", "between", "like".
VALUE is one string or number for =, !=, >, >=, <, <= and like; a list for "in"; and a
[low, high] pair (inclusive) for "between". Dates are "YYYY-MM-DD" strings.
For "which ..." or "top N" questions, include the measure used for ranking, sort by it
descending, and set limit. Use only the fields the question needs."""

FAST_SYSTEM_PROMPT = (
    "You translate a user's analytics question into one semantic query over the explore "
    "described in the prompt. Use only fields listed there. Reply with the JSON object only, "
    "no markdown.\n\n" + SEMANTIC_QUERY_FORMAT
)

FAST_QUERY_PROMPT = """Question:
{question}

Explore description:
{description}

Return JSON shaped like {{"dimensions": [], "measures": [], "filters": [],
"sorts": [], "limit": null}}."""

FAST_SQL_SYSTEM_PROMPT = """Write one read-only DuckDB SELECT statement that answers the question.
Use only the tables and columns in the schema. For "which ..." or "top N" questions, return the
entity and the metric used to rank it. Return SQL only, without explanation."""

FAST_SQL_PROMPT = """Question:
{question}

Table schema:
{schema}
"""


def _string_list(payload: dict, key: str) -> tuple[str, ...]:
    value = payload.get(key, [])
    if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
        raise ProposalError(f"{key!r} must be a list of field names")
    return tuple(value)


def parse_semantic_query(payload: dict, explore: str) -> SemanticQuery:
    """Turn a JSON object from the model into a SemanticQuery.

    Input:  {"dimensions": [...], "measures": [...],
             "filters": [{"field", "op", "value"}], "sorts": [{"field", "descending"}],
             "limit": int | null}. Every key is optional; lists become tuples.
    Output: SemanticQuery(explore=explore, ...).
    Raises: ProposalError on a wrong shape (e.g. "measures" is not a list, unknown op).
    """
    if not isinstance(payload, dict):
        raise ProposalError("the proposal must be a JSON object")
    dimensions = _string_list(payload, "dimensions")
    measures = _string_list(payload, "measures")

    raw_filters = payload.get("filters", [])
    if not isinstance(raw_filters, list):
        raise ProposalError("'filters' must be a list")
    filters: list[Filter] = []
    for index, item in enumerate(raw_filters):
        if not isinstance(item, dict):
            raise ProposalError(f"filter {index} must be an object")
        field = item.get("field")
        op = item.get("op")
        if not isinstance(field, str) or not field:
            raise ProposalError(f"filter {index} needs a field name")
        if not isinstance(op, str) or op not in _FILTER_OPERATORS:
            raise ProposalError(f"filter {index} has an unknown operator")
        if "value" not in item:
            raise ProposalError(f"filter {index} needs a value")
        filters.append(Filter(field, op, item["value"]))

    raw_sorts = payload.get("sorts", [])
    if not isinstance(raw_sorts, list):
        raise ProposalError("'sorts' must be a list")
    sorts: list[Sort] = []
    for index, item in enumerate(raw_sorts):
        if not isinstance(item, dict):
            raise ProposalError(f"sort {index} must be an object")
        field = item.get("field")
        descending = item.get("descending", False)
        if not isinstance(field, str) or not field:
            raise ProposalError(f"sort {index} needs a field name")
        if not isinstance(descending, bool):
            raise ProposalError(f"sort {index} 'descending' must be a boolean")
        sorts.append(Sort(field, descending))

    limit = payload.get("limit")
    if limit is not None and (isinstance(limit, bool) or not isinstance(limit, int)):
        raise ProposalError("'limit' must be an integer or null")
    return SemanticQuery(explore, dimensions, measures, tuple(filters), tuple(sorts), limit)


async def propose_query(
    question: str, layer: SemanticLayer, explore: str, llm: LLMClient, *, model: str
) -> SemanticQuery:
    """Ask the fast model for a semantic query answering `question`.

    Contract:
      - exactly one llm.generate call, with the given `model` and json_mode=True;
      - the prompt contains the question and describe_layer(layer, explore);
      - the reply is parsed with parse_semantic_query and every field is checked with
        resolve_field.
    Raises: ProposalError if the reply is not JSON, has the wrong shape, or names a field
            that does not exist.
    """
    description = describe_layer(layer, explore)
    response = await llm.generate(
        model=model,
        system=FAST_SYSTEM_PROMPT,
        prompt=FAST_QUERY_PROMPT.format(question=question, description=description),
        json_mode=True,
    )
    try:
        payload = json.loads(response.text)
    except (json.JSONDecodeError, TypeError) as exc:
        raise ProposalError("the proposal was not valid JSON") from exc
    query = parse_semantic_query(payload, explore)
    names = [*query.dimensions, *query.measures]
    names.extend(filter_spec.field for filter_spec in query.filters)
    names.extend(sort.field for sort in query.sorts)
    try:
        for name in names:
            resolve_field(layer, name)
    except UnknownFieldError as exc:
        raise ProposalError(str(exc)) from exc
    return query


def _display_value(value: Any, *, round_float: bool = False) -> str:
    if round_float and isinstance(value, float):
        return f"{value:.2f}"
    return str(value)


def render_answer(question: str, query: SemanticQuery, result: QueryResult) -> str:
    """Deterministic (no model call) natural-language rendering of a result.

    Rules the tests check:
      - no rows: the text contains "No results".
      - one row, one column: the text contains that value; floats are rounded to 2 places.
      - otherwise: the text contains the values of the first row, and says how many rows
        there are when there is more than one.
    """
    if not result.rows:
        return f"No results for: {question}"
    first_row = result.rows[0]
    if len(result.rows) == 1 and len(first_row) == 1:
        value = _display_value(first_row[0], round_float=True)
        column = result.columns[0] if result.columns else "value"
        return f"For {question}: {column} is {value}."

    values = ", ".join(_display_value(value) for value in first_row)
    text = f"For {question}, the first row is {values}."
    if len(result.rows) > 1:
        text += f" There are {len(result.rows)} rows."
    return text


async def run_fast_path(
    question: str,
    *,
    layer: SemanticLayer,
    explore: str,
    conn: duckdb.DuckDBPyConnection,
    llm: LLMClient,
    model: str,
) -> FastResult:
    """propose_query -> compile_query -> db.execute -> render_answer.

    latency_ms is wall time for the whole function. Errors from any step propagate.
    """
    start = time.perf_counter()
    query = await propose_query(question, layer, explore, llm, model=model)
    sql = compile_query(query, layer)
    result = db.execute(conn, sql)
    answer_text = render_answer(question, query, result)
    latency_ms = (time.perf_counter() - start) * 1000
    return FastResult(question, query, sql, result, answer_text, latency_ms)


async def propose_sql(question: str, schema: str, llm: LLMClient, *, model: str) -> str:
    """Baseline arm: ask the model for raw SQL directly from the table schema (db.schema_ddl).

    Contract: one llm.generate call with json_mode=False; the prompt contains the question
    and the schema. Strip a surrounding ```sql ... ``` fence and surrounding whitespace, and
    a single trailing semicolon, from the reply.
    """
    response = await llm.generate(
        model=model,
        system=FAST_SQL_SYSTEM_PROMPT,
        prompt=FAST_SQL_PROMPT.format(question=question, schema=schema),
        json_mode=False,
    )
    sql = response.text.strip()
    match = re.fullmatch(r"```sql\s*\n?(.*?)\n?```", sql, flags=re.IGNORECASE | re.DOTALL)
    if match:
        sql = match.group(1).strip()
    if sql.endswith(";"):
        sql = sql[:-1].rstrip()
    return sql
