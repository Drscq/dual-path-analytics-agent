"""Runs the two paths for one question and decides what the user sees, and when.

TODO(Changqi): implement. Tests: tests/test_orchestrator.py.
"""

from __future__ import annotations

import duckdb

from dpa.llm import LLMClient
from dpa.types import Mode, SemanticLayer, Transcript


async def answer(
    question: str,
    *,
    layer: SemanticLayer,
    explore: str,
    conn: duckdb.DuckDBPyConnection,
    llm: LLMClient,
    fast_model: str,
    slow_model: str,
    mode: Mode = "amend",
    hold_deadline_ms: float = 1500,
) -> Transcript:
    """Answer one question. All event times are ms since this function was entered.

    The audit starts as soon as the fast result exists; it runs while the fast answer is
    already on screen, so in "amend" mode it never delays the first answer.

    mode="amend":
      - emit "first" (the fast answer) as soon as the fast path finishes;
      - verdict pass or error: nothing more;
      - verdict fail with a corrected_query: compile + execute it, emit "correction" with the
        re-rendered answer; final_* reflect the corrected query;
      - verdict fail without a corrected_query: emit "caveat" whose text names the issues;
        final_* stay the fast ones.
    mode="hold":
      - wait for the verdict, but no longer than hold_deadline_ms after the fast path finished;
      - verdict arrives in time: emit exactly one "first" event carrying the best answer
        (the corrected one on fail-with-correction, else the fast one; a fail without
        correction adds a "caveat" after it);
      - deadline passes first: emit the fast answer as "first" at the deadline, then continue
        exactly as in amend mode.
    If the corrected query fails to compile or execute, treat it as fail-without-correction.
    The Transcript always carries fast, verdict (None only if the audit never finished),
    final_query and final_result.
    """
    raise NotImplementedError
