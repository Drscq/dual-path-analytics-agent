"""Slow path: a stronger model audits what the fast path did and may propose a corrected query.

TODO(Changqi): implement. Tests: tests/test_slow_path.py.
"""

from __future__ import annotations

from dpa.llm import LLMClient
from dpa.types import FastResult, SemanticLayer, Verdict

MAX_ROWS_SHOWN = 20
ISSUE_KINDS = (
    "wrong_field", "missing_filter", "wrong_filter", "wrong_aggregation", "wrong_time_window", "other"
)


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
    raise NotImplementedError
