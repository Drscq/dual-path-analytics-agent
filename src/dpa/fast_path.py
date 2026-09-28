"""Fast path: question -> semantic query -> SQL -> result -> answer text, with one cheap model call.

TODO(Changqi): implement every function. Tests: tests/test_fast_path.py.
"""

from __future__ import annotations

import duckdb

from dpa.llm import LLMClient
from dpa.types import FastResult, QueryResult, SemanticLayer, SemanticQuery


class ProposalError(ValueError):
    """The model's output could not be turned into a valid query."""


def parse_semantic_query(payload: dict, explore: str) -> SemanticQuery:
    """Turn a JSON object from the model into a SemanticQuery.

    Input:  {"dimensions": [...], "measures": [...],
             "filters": [{"field", "op", "value"}], "sorts": [{"field", "descending"}],
             "limit": int | null}. Every key is optional; lists become tuples.
    Output: SemanticQuery(explore=explore, ...).
    Raises: ProposalError on a wrong shape (e.g. "measures" is not a list, unknown op).
    """
    raise NotImplementedError


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
    raise NotImplementedError


def render_answer(question: str, query: SemanticQuery, result: QueryResult) -> str:
    """Deterministic (no model call) natural-language rendering of a result.

    Rules the tests check:
      - no rows: the text contains "No results".
      - one row, one column: the text contains that value; floats are rounded to 2 places.
      - otherwise: the text contains the values of the first row, and says how many rows
        there are when there is more than one.
    """
    raise NotImplementedError


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
    raise NotImplementedError


async def propose_sql(question: str, schema: str, llm: LLMClient, *, model: str) -> str:
    """Baseline arm: ask the model for raw SQL directly from the table schema (db.schema_ddl).

    Contract: one llm.generate call with json_mode=False; the prompt contains the question
    and the schema. Strip a surrounding ```sql ... ``` fence and surrounding whitespace, and
    a single trailing semicolon, from the reply.
    """
    raise NotImplementedError
