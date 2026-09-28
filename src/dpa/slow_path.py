"""Slow path: a stronger model audits what the fast path did and may propose a corrected query.

Tests: tests/test_slow_path.py.
"""

from __future__ import annotations

import json
import time
from typing import Any

from dpa.fast_path import SEMANTIC_QUERY_FORMAT, ProposalError, parse_semantic_query
from dpa.llm import LLMClient
from dpa.semantic import UnknownFieldError, describe_layer, resolve_field
from dpa.types import FastResult, Issue, SemanticLayer, SemanticQuery, Verdict

MAX_ROWS_SHOWN = 20
ISSUE_KINDS = (
    "wrong_field", "missing_filter", "wrong_filter", "wrong_aggregation", "wrong_time_window", "other"
)

SLOW_SYSTEM_PROMPT = (
    "You audit an analytics answer for correctness against the user's question and the "
    "semantic layer. Set ok=true only when the query and its result answer the question as "
    "asked. If not, list specific issues (kind is one of: " + ", ".join(ISSUE_KINDS) + ") and "
    "give corrected_query, a full replacement semantic query, whenever you can. Use only fields "
    "in the explore description. Reply with the JSON object only, no markdown.\n\n"
    + SEMANTIC_QUERY_FORMAT
)

SLOW_AUDIT_PROMPT = """Question:
{question}

Fast semantic query (JSON):
{query_json}

Compiled SQL:
{sql}

Result preview (up to {max_rows} rows):
{result_json}

Explore description:
{description}

Return JSON shaped like {{"ok": false, "issues": [{{"kind": "missing_filter",
"detail": "..."}}], "corrected_query": null}}."""


def _query_payload(query: SemanticQuery) -> dict[str, Any]:
    return {
        "dimensions": list(query.dimensions),
        "measures": list(query.measures),
        "filters": [
            {"field": item.field, "op": item.op, "value": item.value}
            for item in query.filters
        ],
        "sorts": [
            {"field": item.field, "descending": item.descending}
            for item in query.sorts
        ],
        "limit": query.limit,
    }


def _validate_query_fields(query: SemanticQuery, layer: SemanticLayer) -> None:
    names = [*query.dimensions, *query.measures]
    names.extend(item.field for item in query.filters)
    names.extend(item.field for item in query.sorts)
    for name in names:
        resolve_field(layer, name)


def _error_verdict(start: float, message: str) -> Verdict:
    latency_ms = (time.perf_counter() - start) * 1000
    return Verdict(status="error", latency_ms=latency_ms, error=message or "audit failed")


async def audit(
    fast: FastResult, *, layer: SemanticLayer, explore: str, llm: LLMClient, model: str
) -> Verdict:
    """Audit one fast-path answer.

    Contract:
      - exactly one llm.generate call with the given `model` and json_mode=True;
      - the prompt contains the question, the semantic query (as JSON), the compiled SQL,
        at most MAX_ROWS_SHOWN result rows, and describe_layer(layer, explore);
      - expected reply: {"ok": bool,
                         "issues": [{"kind": str, "detail": str}],
                         "corrected_query": {...same shape as the fast path's...} | null}
    Output:
      - ok true  -> Verdict(status="pass"), issues and correction ignored;
      - ok false -> Verdict(status="fail", issues=..., corrected_query=...), where an unknown
        issue kind becomes "other", and a corrected_query that fails parsing or names an
        unknown field is dropped (None) but the verdict stays "fail";
      - reply not JSON / wrong shape / the call raises -> Verdict(status="error", error=<msg>).
        The audit must never raise: a broken auditor must not break the answer.
      - latency_ms is wall time of the whole function.
    """
    start = time.perf_counter()
    try:
        query_json = json.dumps(_query_payload(fast.query), default=str, sort_keys=True)
        result_json = json.dumps(
            {
                "columns": fast.result.columns,
                "rows": fast.result.rows[:MAX_ROWS_SHOWN],
            },
            default=str,
        )
        description = describe_layer(layer, explore)
        prompt = SLOW_AUDIT_PROMPT.format(
            question=fast.question,
            query_json=query_json,
            sql=fast.sql,
            result_json=result_json,
            max_rows=MAX_ROWS_SHOWN,
            description=description,
        )
        response = await llm.generate(
            model=model,
            system=SLOW_SYSTEM_PROMPT,
            prompt=prompt,
            json_mode=True,
        )
        reply = json.loads(response.text)
        if not isinstance(reply, dict) or not isinstance(reply.get("ok"), bool):
            raise TypeError("audit reply must be an object with a boolean 'ok' value")
        if reply["ok"]:
            return Verdict(status="pass", latency_ms=(time.perf_counter() - start) * 1000)

        raw_issues = reply.get("issues", [])
        if not isinstance(raw_issues, list):
            raise TypeError("audit 'issues' must be a list")
        issues: list[Issue] = []
        for index, item in enumerate(raw_issues):
            if not isinstance(item, dict):
                raise TypeError(f"audit issue {index} must be an object")
            kind = item.get("kind")
            detail = item.get("detail")
            if not isinstance(kind, str) or not isinstance(detail, str):
                raise TypeError(f"audit issue {index} needs string kind and detail values")
            if kind not in ISSUE_KINDS:
                kind = "other"
            issues.append(Issue(kind, detail))

        corrected: SemanticQuery | None = None
        corrected_payload = reply.get("corrected_query")
        if corrected_payload is not None:
            try:
                corrected = parse_semantic_query(corrected_payload, explore)
                _validate_query_fields(corrected, layer)
            except (ProposalError, UnknownFieldError):
                corrected = None
        return Verdict(
            status="fail",
            issues=tuple(issues),
            corrected_query=corrected,
            latency_ms=(time.perf_counter() - start) * 1000,
        )
    except Exception as exc:  # noqa: BLE001 -- the audit contract turns all failures into verdicts
        return _error_verdict(start, str(exc) or type(exc).__name__)
