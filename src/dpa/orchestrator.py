"""Runs the two paths for one question and decides what the user sees, and when.

Tests: tests/test_orchestrator.py.
"""

from __future__ import annotations

import asyncio
import time

import duckdb

from dpa import db
from dpa.fast_path import render_answer, run_fast_path
from dpa.llm import LLMClient
from dpa.semantic import compile_query
from dpa.slow_path import audit
from dpa.types import (
    AnswerEvent,
    FastResult,
    Mode,
    QueryResult,
    SemanticLayer,
    SemanticQuery,
    Transcript,
    Verdict,
)


def _event_time(start: float) -> float:
    return (time.perf_counter() - start) * 1000


def _caveat_text(verdict: Verdict) -> str:
    details = [f"{issue.kind}: {issue.detail}" for issue in verdict.issues]
    if not details:
        details.append("the auditor did not provide issue details")
    return "The audit could not correct the answer. Issues: " + "; ".join(details)


def _try_correction(
    verdict: Verdict,
    *,
    question: str,
    layer: SemanticLayer,
    conn: duckdb.DuckDBPyConnection,
) -> tuple[SemanticQuery, QueryResult, str] | None:
    if verdict.status != "fail" or verdict.corrected_query is None:
        return None
    query = verdict.corrected_query
    try:
        sql = compile_query(query, layer)
        result = db.execute(conn, sql)
        text = render_answer(question, query, result)
    except Exception:  # noqa: BLE001 -- any correction compile or execution failure becomes a caveat
        return None
    return query, result, text


def _set_correction(transcript: Transcript, correction: tuple[SemanticQuery, QueryResult, str]) -> None:
    query, result, _ = correction
    transcript.final_query = query
    transcript.final_result = result


def _append_followup(
    transcript: Transcript,
    verdict: Verdict,
    correction: tuple[SemanticQuery, QueryResult, str] | None,
    start: float,
) -> None:
    if verdict.status != "fail":
        return
    if correction is not None:
        _set_correction(transcript, correction)
        transcript.events.append(AnswerEvent("correction", correction[2], _event_time(start)))
    else:
        transcript.events.append(AnswerEvent("caveat", _caveat_text(verdict), _event_time(start)))


async def _completed_verdict(task: asyncio.Task[Verdict]) -> Verdict:
    try:
        return await task
    except Exception as exc:  # noqa: BLE001 -- convert any unexpected audit failure to a verdict
        return Verdict(status="error", error=str(exc) or type(exc).__name__)


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
    fast_explores: tuple[str, ...] | None = None,
    audit_explores: tuple[str, ...] | None = None,
    value_lookup=None,
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
    if mode not in ("amend", "hold"):
        raise ValueError(f"unknown answer mode {mode!r}")
    start = time.perf_counter()
    transcript = Transcript(question=question, mode=mode)
    fast: FastResult = await run_fast_path(
        question,
        layer=layer,
        explore=explore,
        conn=conn,
        llm=llm,
        model=fast_model,
        explores=fast_explores,
    )
    fast_finished = time.perf_counter()
    transcript.fast = fast
    transcript.final_query = fast.query
    transcript.final_result = fast.result

    audit_task = asyncio.create_task(
        audit(fast, layer=layer, explore=explore, llm=llm, model=slow_model,
              explores=audit_explores, value_lookup=value_lookup)
    )
    if mode == "amend":
        transcript.events.append(AnswerEvent("first", fast.answer_text, _event_time(start)))
        verdict = await _completed_verdict(audit_task)
        transcript.verdict = verdict
        correction = _try_correction(
            verdict, question=question, layer=layer, conn=conn
        )
        _append_followup(transcript, verdict, correction, start)
        return transcript

    remaining_s = max(0.0, hold_deadline_ms / 1000 - (time.perf_counter() - fast_finished))
    done, _ = await asyncio.wait({audit_task}, timeout=remaining_s)
    if audit_task in done:
        verdict = await _completed_verdict(audit_task)
        transcript.verdict = verdict
        correction = _try_correction(
            verdict, question=question, layer=layer, conn=conn
        )
        if correction is not None:
            _set_correction(transcript, correction)
            first_text = correction[2]
        else:
            first_text = fast.answer_text
        transcript.events.append(AnswerEvent("first", first_text, _event_time(start)))
        if verdict.status == "fail" and correction is None:
            transcript.events.append(AnswerEvent("caveat", _caveat_text(verdict), _event_time(start)))
        return transcript

    transcript.events.append(AnswerEvent("first", fast.answer_text, _event_time(start)))
    verdict = await _completed_verdict(audit_task)
    transcript.verdict = verdict
    correction = _try_correction(verdict, question=question, layer=layer, conn=conn)
    _append_followup(transcript, verdict, correction, start)
    return transcript
