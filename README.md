# dual-path-analytics-agent

## Objective

Conversational analytics has two goals that pull against each other: answer **fast**, and answer
**right**. This project tests one way to get both: a fast model answers immediately, and a stronger
model audits that answer *while it is already on screen*, sending a correction only when it finds
a mistake. The questions it answers:

1. Does grounding the model in a **semantic layer** (LookML-style metrics and dimensions) beat
   letting it write SQL directly?
2. Does a **slow-path audit** improve accuracy, and what does it cost in latency and money?
3. Should the user see the fast answer at once and a correction later (**amend**), or wait for the
   audit (**hold**)?

Data: [thelook_ecommerce](https://console.cloud.google.com/marketplace/product/bigquery-public-data/thelook-ecommerce)
(Looker's demo dataset; 182k order items, 125k orders, 100k users) in DuckDB.
Models: `gemini-3.8-flash` (fast) and `gemini-3.1-pro-preview` (slow).

## Results (round 1, 2026-09-28)

30 questions ([evals/cases.jsonl](evals/cases.jsonl)), each with gold SQL checked on the data;
an answer counts as correct if its result matches the gold result (execution match).

| Configuration | What runs | Accuracy | Time to first answer p50 / p95 | Time to final answer p50 / p95 | Cost / question |
|---|---|---|---|---|---|
| `direct_sql` | Flash writes SQL from the table schema | **70%** | 3.96 s / 30.8 s | 3.96 s / 30.8 s | $0.0083 |
| `fast_only` | Flash → semantic query → compiled SQL | **100%** | 1.88 s / 2.54 s | 1.88 s / 2.54 s | $0.0020 |
| `amend_flash` | fast path + Flash audit, amend | **100%** | 1.71 s / 2.34 s | 1.71 s / 2.34 s | $0.0042 |
| `amend_pro` | fast path + Pro audit, amend | **100%** | 1.74 s / 2.27 s | 1.74 s / 2.27 s | $0.0070 |
| `hold3000_flash` | same audits, shown only after the verdict (≤ 3 s) | 100% | 3.46 s / 5.26 s | 3.46 s / 5.26 s | $0.0042 |
| `hold3000_pro` | same, Pro | 100% | 4.38 s / 5.27 s | 4.38 s / 5.27 s | $0.0070 |

**Findings**

- **The semantic layer is the big win**: 70% → 100% accuracy, p95 latency 30.8 s → 2.5 s, and a
  quarter of the cost. The direct-SQL errors were not syntax errors: the model applied its own
  business definitions, e.g. excluding cancelled and returned items from "revenue", counting
  "returned in a year" by return date, or counting customers from the orders table. The semantic
  layer pins those definitions down; that is its job.
- **The audit never fired, and never raised a false alarm.** On this set the fast answer was
  already right every time, and both auditors passed all 30 answers. In amend mode that meant no
  cost to the user (first-answer latency unchanged, within noise) for $0.002–0.005 per question.
- **Hold mode only adds waiting here**: +1.7 s (Flash audit) to +2.6 s (Pro audit) at p50 for the
  same accuracy.
- **Recommended default: `amend_flash`.** It is as fast as no audit, cheaper than a Pro audit, and
  did not raise a single false alarm. Whether a Pro audit earns its extra cost is exactly what
  round 2 has to show.

**Limitations.** The 30 questions are phrased unambiguously, so the fast path hits a ceiling and
the audit is untested on answers that are actually wrong. One run per configuration; `direct_sql`
is not deterministic (2 of its 9 misses flipped on a re-run). Hold-mode rows are derived from the
amend runs' recorded fast, audit and correction times rather than run separately
(`scripts/run_eval.py report`). Raw records: [results/2026-09-28](results/2026-09-28).

**Next (round 2).** A harder question set built to make the fast path fail: implicit business
rules, relative dates ("last quarter"), fan-out traps, and ambiguous wording. That is where the
slow path has to prove it is worth its cost.

## How it works

- **Fast path**: the fast model turns the question into a *semantic query* over a LookML-style
  semantic layer; deterministic code compiles it to SQL and runs it on DuckDB.
- **Slow path**: while the first answer is already on screen, a stronger model audits the query and
  its result (wrong field, missing filter, wrong aggregation, wrong time window) and may propose a
  corrected query, which is shown as a correction.
- **Evaluation**: execution accuracy against gold SQL, and p50/p95 of both *time to first answer*
  and *time to final answer*. For answers that cannot be execution-matched, a model judge is used
  only after it is checked against hand labels (Cohen's kappa, calibration error).

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
