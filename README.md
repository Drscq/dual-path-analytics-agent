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

**Next (round 2).** A harder question set built to make the fast path fail — see below.

## Results (round 2, 2026-10-02): a harder set

30 new questions ([evals/cases_round2.jsonl](evals/cases_round2.jsonl)) built to make the fast path
fail: value mapping ("Brazil" is stored as `Brasil`, "female" as `F`), implicit rules ("revenue we
kept" = without cancelled and returned items; "in transit" = `Shipped`), fan-out traps (orders or
customers counted through item rows), quarter and half-year windows, relative dates anchored by
"Today is ...", order date vs item date, ranking direction, and one data-quality case (`Germany`
and `Deutschland` both occur). Every gold SQL was run on the data, and the trap answers were checked
to differ from the gold ones.

| Configuration | Accuracy | Time to first answer p50 / p95 | Time to final answer p50 / p95 | Cost / question |
|---|---|---|---|---|
| `direct_sql` | **73%** | 3.51 s / 32.1 s | 3.51 s / 32.1 s | $0.0087 |
| `fast_only` | **87%** | 2.22 s / 5.16 s | 2.22 s / 5.16 s | $0.0026 |
| `amend_flash` | 87% | 2.26 s / 10.2 s | 2.26 s / 10.2 s | $0.0059 |
| `amend_pro` | 87% | 2.55 s / 8.40 s | 2.55 s / 8.40 s | $0.0082 |
| `hold3000_flash` | 87% | 4.73 s / 13.0 s | 4.73 s / 13.0 s | $0.0059 |
| `hold3000_pro` | 87% | 5.55 s / 11.4 s | 5.55 s / 11.4 s | $0.0082 |

**Findings**

- **The semantic layer still wins**, 87% vs 73%, at under a third of the cost and a sixth of the
  p95 latency. Direct SQL fell into the traps the layer is there to close: `'Brazil'`, an off-by-one
  quarter boundary, a wrong sort direction, item rows counted as products.
- **All four fast-path misses have one root cause, and it is in the layer, not the model.** Every
  question about *customers* ("How many customers are based in Brazil?", "How many female
  customers do we have?", "Which 5 US states have the most customers?") was answered through the
  only explore, which starts at `order_items`. The compiled SQL is correct for that explore, but it
  can only see customers who have bought something: 11,640 of the 14,507 customers in Brazil,
  40,152 of 50,208 female customers. The model mapped `Brasil` and `F` correctly.
- **The audit passed all four wrong answers, with no issue raised, under both auditors.** It
  checks the query against the explore it is given, and that explore makes the wrong population
  look right. A slow model cannot catch an error that the semantic layer itself encodes.
- `Germany` vs `Deutschland` is missed by every configuration: no part of the system sees the
  stored values.

**Next (round 3).** Give questions about customers their own explore, let the fast path pick the
explore, and show the auditor the explore's base grain and the stored filter values — see below.

## Results (round 3, 2026-10-02): fixing the population, and an audit that can see it

Two changes, both aimed at the round-2 failures:

1. **A second explore and explore choice.** `users` is now an explore of its own (customers,
   including those who never ordered, with items, orders and products joined one-to-many), and the
   fast model picks the explore whose base view is the population the question counts.
2. **More context for the audit, not for the fast path.** The auditor is told which explore was
   used and what its base view is, sees the other explores, and may return a corrected query on a
   different explore ("population check"). For every string dimension the query filters on, it also
   sees the values actually stored (up to 60, read from the dimension's own table).

Same 30 hard questions as round 2 ([evals/cases_round2.jsonl](evals/cases_round2.jsonl)):

| Configuration | First-answer accuracy | Final accuracy | Fixed / broke | Time to first answer p50 / p95 | Cost / question |
|---|---|---|---|---|---|
| round 2 `fast_only` (one explore) | 87% | 87% | – | 2.22 s / 5.16 s | $0.0026 |
| `fast_only_r3` (explore choice) | **97%** | 97% | – | 2.30 s / 16.5 s | $0.0047 |
| `amend_flash_r3` | 97% | **100%** | 1 / 0 | 2.48 s / 16.6 s | $0.0084 |
| `amend_pro_r3` | 97% | **100%** | 1 / 0 | 2.40 s / 12.0 s | $0.0110 |
| `amend_pro_r3auditonly` (old fast path, new audit) | 87% | **100%** | **4 / 0** | 2.31 s / 9.33 s | $0.0112 |

Regression check on the round-1 set ([evals/cases.jsonl](evals/cases.jsonl)): `fast_only_r3` and
`amend_pro_r3` both 100%, no audit fired, no false alarm. Raw records:
[results/2026-10-02-round3](results/2026-10-02-round3).

**Findings**

- **Explore choice fixes the population errors at the source**: the fast path went from 87% to
  97%; the three customer-population misses are gone. The one it still misses is `Germany` vs
  `Deutschland`, which no amount of schema knowledge reveals.
- **The audit now catches what the fast path cannot.** With stored values in view, both auditors
  flagged the `Germany` filter (`wrong_filter`), corrected it to both spellings, and brought the
  final answer to 100%. The correction arrives after the first answer (p50 first answer unchanged).
- **The audit-only run isolates the slow path's value**: keeping the round-2 fast path (one
  explore) and upgrading only the auditor, Pro caught **all four** round-2 misses (three as
  `wrong_field` with a switch to the `users` explore, one as `wrong_filter`), fixed every one, and
  raised **no false alarm** on the 26 correct answers. The round-2 audit had passed all four.
- **What it costs.** Showing two explores roughly doubles the fast path's prompt: $0.0026 →
  $0.0047 per question, and a heavier latency tail (p95 5.2 s → 16.5 s, from four slow model
  responses; one run, so the tail is noisy). The Flash auditor raised one false alarm (it
  re-wrote a correct `Memphis TN` filter; the answer stayed correct), the Pro auditor none.
- **Takeaway for the design**: the semantic layer decides what *can* be right; the audit is only
  as good as the context it is given. Grain and stored values are cheap context that turned the
  audit from never firing into the component that closes the last errors.

## How it works

- **Fast path**: the fast model turns the question into a *semantic query* over a LookML-style
  semantic layer; deterministic code compiles it to SQL and runs it on DuckDB.
- **Slow path**: while the first answer is already on screen, a stronger model audits the query and
  its result (wrong field, missing filter, wrong aggregation, wrong time window) and may propose a
  corrected query, which is shown as a correction. Since round 3 it also sees the explore's base
  view (population check) and the stored values of filtered string dimensions, and its correction
  may move to another explore.
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
