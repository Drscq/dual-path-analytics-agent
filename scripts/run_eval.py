"""Run the eval set under one configuration, or compare finished runs.

  python scripts/run_eval.py run --config amend_pro [--limit N] [--budget 4.0]
  python scripts/run_eval.py report runs/*.jsonl [--hold-deadline-ms 3000]

Configurations
  direct_sql    fast model writes raw SQL from the table schema (no semantic layer, no audit)
  fast_only     fast path over the semantic layer, no audit
  amend_pro     fast path + audit by the slow (Pro) model, amend mode
  amend_flash   fast path + audit by the fast model itself, amend mode

Hold mode is not run separately: every amend record carries the fast latency, the audit latency
and the correction time, so `report` derives what hold mode with a given deadline would have
shown, without paying for the same audits twice.

Runs are sequential so latencies are not distorted by our own concurrency. Spend is estimated
from token counts (thinking included) and the run stops once --budget USD is reached.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
from dataclasses import asdict, dataclass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from dpa import db
from dpa.config import Models, load_api_key
from dpa.eval.cases import load_cases
from dpa.eval.metrics import RunRecord, results_match, summarize
from dpa.fast_path import propose_sql, run_fast_path
from dpa.llm import GeminiClient, LLMResponse
from dpa.orchestrator import answer
from dpa.semantic import load_semantic_layer

LAYER = Path("semantic/thelook.yaml")
EXPLORE = "order_items"
CONFIGS = ("direct_sql", "fast_only", "amend_pro", "amend_flash")
# USD per 1M tokens (input, output incl. thinking); ai.google.dev/gemini-api/docs/pricing, 2026-09.
PRICES = {"flash": (0.75, 3.75), "pro": (2.00, 12.00)}


class MeteredLLM:
    """Wraps an LLM client and keeps a running cost estimate per model."""

    def __init__(self, inner):
        self.inner = inner
        self.usd = 0.0
        self.tokens = {"in": 0, "out": 0}

    async def generate(self, *, model, system, prompt, json_mode=False) -> LLMResponse:
        r = await self.inner.generate(model=model, system=system, prompt=prompt,
                                      json_mode=json_mode)
        pin, pout = PRICES["pro" if "pro" in model else "flash"]
        self.usd += (r.input_tokens * pin + r.output_tokens * pout) / 1e6
        self.tokens["in"] += r.input_tokens
        self.tokens["out"] += r.output_tokens
        return r


@dataclass
class Row:
    """One case under one configuration. Times are ms since the question arrived."""

    config: str
    case_id: str
    fast_correct: bool
    final_correct: bool
    corrected: bool
    t_first: float
    t_final: float
    fast_ms: float | None = None  # when the fast answer was ready
    audit_ms: float | None = None  # duration of the audit itself
    verdict: str | None = None
    issues: list[str] | None = None
    error: str | None = None


async def run_case(config, case, gold, *, layer, conn, llm, models, schema) -> Row:
    start = time.perf_counter()

    def ms():
        return (time.perf_counter() - start) * 1000

    def match(result):
        return results_match(result, gold, order_matters=case.order_matters)

    try:
        if config == "direct_sql":
            sql = await propose_sql(case.question, schema, llm, model=models.fast)
            ok = match(db.execute(conn, sql))
            t = ms()
            return Row(config, case.id, ok, ok, False, t, t, fast_ms=t)
        if config == "fast_only":
            fr = await run_fast_path(case.question, layer=layer, explore=EXPLORE, conn=conn,
                                     llm=llm, model=models.fast)
            ok = match(fr.result)
            return Row(config, case.id, ok, ok, False, fr.latency_ms, fr.latency_ms,
                       fast_ms=fr.latency_ms)
        slow = models.slow if config == "amend_pro" else models.fast
        t = await answer(case.question, layer=layer, explore=EXPLORE, conn=conn, llm=llm,
                         fast_model=models.fast, slow_model=slow, mode="amend")
        v = t.verdict
        return Row(
            config, case.id,
            fast_correct=match(t.fast.result),
            final_correct=match(t.final_result),
            corrected=any(e.kind == "correction" for e in t.events),
            t_first=t.time_to_first_ms, t_final=t.time_to_final_ms,
            fast_ms=t.events[0].t_ms,
            audit_ms=v.latency_ms if v else None,
            verdict=v.status if v else None,
            issues=[i.kind for i in v.issues] if v else None,
        )
    except Exception as e:  # noqa: BLE001 - a failed answer is a wrong answer; keep going
        t = ms()
        err = f"{type(e).__name__}: {e}"[:300]
        return Row(config, case.id, False, False, False, t, t, error=err)


async def run(args) -> None:
    layer = load_semantic_layer(LAYER)
    conn = db.connect()
    schema = db.schema_ddl(conn)
    cases = load_cases(args.cases)[: args.limit]
    llm = MeteredLLM(GeminiClient(load_api_key()))
    models = Models.from_env()
    out = Path("runs") / f"{time.strftime('%Y%m%d-%H%M%S')}-{args.config}.jsonl"
    out.parent.mkdir(exist_ok=True)
    print(f"{args.config}: {len(cases)} cases, fast={models.fast} slow={models.slow} -> {out}")
    with out.open("w") as f:
        for i, case in enumerate(cases, 1):
            gold = db.execute(conn, case.gold_sql)
            row = await run_case(args.config, case, gold, layer=layer, conn=conn, llm=llm,
                                 models=models, schema=schema)
            f.write(json.dumps(asdict(row)) + "\n")
            f.flush()
            mark = "ok " if row.final_correct else ("ERR" if row.error else "x  ")
            fix = " (corrected)" if row.corrected else ""
            print(f"  [{i:2d}/{len(cases)}] {mark} {case.id:24s} first {row.t_first:7.0f} ms  "
                  f"final {row.t_final:7.0f} ms{fix}  spend ${llm.usd:.3f}"
                  + (f"  {row.error[:80]}" if row.error else ""))
            if llm.usd >= args.budget:
                print(f"budget ${args.budget} reached, stopping")
                break
    print(f"estimated spend ${llm.usd:.3f}  tokens {llm.tokens}")


# --- report -------------------------------------------------------------------------------


def to_record(r: dict) -> RunRecord:
    return RunRecord(r["case_id"], r["fast_correct"], r["final_correct"], r["corrected"],
                     r["t_first"], r["t_final"])


def hold_view(r: dict, deadline_ms: float) -> RunRecord:
    """What hold mode would have shown for an amend record."""
    if r["audit_ms"] is not None and r["audit_ms"] <= deadline_ms:
        shown_at = r["t_final"] if r["corrected"] else r["fast_ms"] + r["audit_ms"]
        return RunRecord(r["case_id"], r["final_correct"], r["final_correct"], False,
                         shown_at, shown_at)
    first = r["fast_ms"] + deadline_ms if r["fast_ms"] is not None else r["t_first"]
    return RunRecord(r["case_id"], r["fast_correct"], r["final_correct"], r["corrected"],
                     first, max(first, r["t_final"]))


def report(args) -> None:
    rows_by_name: dict[str, list[RunRecord]] = {}
    for path in args.files:
        rows = [json.loads(line) for line in Path(path).read_text().splitlines() if line]
        if not rows:
            continue
        name = rows[0]["config"]
        rows_by_name[name] = [to_record(r) for r in rows]
        if name.startswith("amend"):
            d = args.hold_deadline_ms
            rows_by_name[f"hold{int(d)}_{name[6:]}"] = [hold_view(r, d) for r in rows]
        errors = sum(1 for r in rows if r["error"])
        if errors:
            print(f"{name}: {errors} case(s) errored (counted as wrong)")

    head = (f"{'config':18s} {'n':>3s} {'first acc':>9s} {'final acc':>9s} {'fixed':>5s} "
            f"{'broke':>5s} {'p50 first':>9s} {'p95 first':>9s} {'p50 final':>9s} "
            f"{'p95 final':>9s}")
    print(head)
    print("-" * len(head))
    for name, recs in rows_by_name.items():
        s = summarize(recs)
        print(f"{name:18s} {s.n:3d} {s.fast_accuracy:9.0%} {s.final_accuracy:9.0%} {s.fixed:5d} "
              f"{s.broke:5d} {s.p50_first_ms:9.0f} {s.p95_first_ms:9.0f} {s.p50_final_ms:9.0f} "
              f"{s.p95_final_ms:9.0f}")


def main() -> None:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run")
    r.add_argument("--config", choices=CONFIGS, required=True)
    r.add_argument("--cases", default="evals/cases.jsonl")
    r.add_argument("--limit", type=int)
    r.add_argument("--budget", type=float, default=4.0)
    p = sub.add_parser("report")
    p.add_argument("files", nargs="+")
    p.add_argument("--hold-deadline-ms", type=float, default=3000)
    args = ap.parse_args()
    if args.cmd == "run":
        asyncio.run(run(args))
    else:
        report(args)


if __name__ == "__main__":
    main()
