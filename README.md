# dual-path-analytics-agent

A conversational analytics agent that answers natural-language questions about e-commerce data
([thelook_ecommerce](https://console.cloud.google.com/marketplace/product/bigquery-public-data/thelook-ecommerce)),
built around one trade-off: **answer fast, then check**.

- **Fast path**: a fast Gemini model turns the question into a *semantic query* over a
  LookML-style semantic layer; deterministic code compiles it to SQL and runs it on DuckDB.
- **Slow path**: while the first answer is already on screen, a stronger model audits the query and
  its result (wrong field, missing filter, wrong aggregation, wrong time window) and may propose a
  corrected query, which is shown as a correction.
- **Evaluation**: execution accuracy against hand-written gold SQL, and p50/p95 of both
  *time to first answer* and *time to final answer*, across ablations (amend vs hold mode,
  semantic layer vs direct SQL, with and without the slow path). A model judge handles answers
  that cannot be execution-matched, and is itself checked against hand labels
  (Cohen's kappa, calibration error) before its grades are used.

Vocabulary is defined in [CONTEXT.md](CONTEXT.md); design decisions live in [docs/adr](docs/adr).

## Setup

```bash
make setup          # venv + dependencies
make data           # download the CSV snapshot, build data/thelook.duckdb (not committed)
make test           # unit tests; no API key needed
```

The Gemini API key is read from `GEMINI_API_KEY`, or from the macOS keychain:

```bash
security add-generic-password -a "$USER" -s GEMINI_API_KEY -T "" -w
```

Model ids default to `gemini-3.8-flash` (fast) and `gemini-3.1-pro-preview` (slow); override
with `DPA_FAST_MODEL` / `DPA_SLOW_MODEL`.

## Layout

| Path | What |
|---|---|
| `src/dpa/types.py` | Shared value types |
| `src/dpa/semantic.py` | Load / validate / describe the semantic layer; compile semantic queries to SQL |
| `src/dpa/fast_path.py` | Question → semantic query → SQL → result → answer; direct-SQL baseline |
| `src/dpa/slow_path.py` | Audit of a fast-path answer → verdict |
| `src/dpa/orchestrator.py` | Runs both paths; amend and hold modes; event timing |
| `src/dpa/eval/` | Eval cases, execution match, latency percentiles, judge agreement |
| `src/dpa/llm.py`, `db.py`, `data.py`, `config.py` | Model client (+ a scripted fake for tests), DuckDB, data build, key lookup |
| `semantic/thelook.yaml` | The semantic layer |
| `evals/` | Eval cases (JSONL) |

## Status

The core modules (`semantic`, `fast_path`, `slow_path`, `orchestrator`, `eval`) were implemented
with an AI coding agent against the docstring specs and tests written first, then verified:
the tests were left untouched, and an independent set of edge-case checks (SQL escaping, minimal
joins, fan-out-safe counts, metric functions against reference implementations, concurrency of
the two paths) was run against the result.

Run an evaluation:

```bash
python scripts/run_eval.py run --config fast_only     # direct_sql | fast_only | amend_flash | amend_pro
python scripts/run_eval.py report runs/*.jsonl --hold-deadline-ms 3000
```

## License

MIT
