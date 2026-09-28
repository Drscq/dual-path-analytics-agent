# Dual-Path Analytics Agent

Answers natural-language questions about business data by querying a semantic layer, with a fast path that answers first and a slow path that checks the answer afterwards.

## Language

### Data model

**Semantic layer**:
The curated description of the data that questions are answered against: views, their dimensions and measures, and explores.
_Avoid_: schema, data model, metadata

**View**:
One table of the database as seen through the semantic layer, with its dimensions and measures.
_Avoid_: table (the physical thing a view points at), entity

**Dimension**:
An attribute of a view that answers can be grouped or filtered by, such as country or order status.
_Avoid_: column, attribute, field (when the kind matters)

**Measure**:
An aggregate defined on a view, such as total sale price or number of orders.
_Avoid_: metric, KPI, aggregate

**Field**:
A dimension or a measure, always named as "view.field".

**Primary key**:
The dimension that identifies one row of a view; counts are taken over it so joins never inflate them.

**Explore**:
A starting view plus the views joined to it; it bounds which fields one question may use.
_Avoid_: dataset, model, join graph

**Fan-out**:
The row multiplication that happens when a one-to-many join repeats a row, which would inflate a naive count or sum.

### Answering

**Question**:
A natural-language request for data from a user.
_Avoid_: prompt, query (reserved for semantic query)

**Semantic query**:
The structured request (fields, filters, sorts, limit) that a question is turned into before any SQL exists.
_Avoid_: query plan, intent, SQL

**Fast path**:
The low-latency route from a question to a first answer, using a cheaper model.
_Avoid_: S1, drafter, generator

**Slow path**:
The audit of a fast-path answer by a stronger model, which may produce a corrected semantic query.
_Avoid_: S2, verifier, critic, reviewer

**Verdict**:
The slow path's judgement of one answer: pass, fail, or error.

**Issue**:
One specific problem a verdict names, such as a missing filter or a wrong aggregation.

**Correction**:
A replacement answer shown after the first answer because the slow path failed it and supplied a corrected semantic query.
_Avoid_: repair, fix, retry

**Caveat**:
A warning shown after the first answer when the slow path failed it but could not supply a correction.

**Amend mode**:
Show the fast answer immediately and follow it with a correction or caveat if needed.

**Hold mode**:
Wait for the verdict up to a deadline before showing anything, then fall back to amend mode.

**Time to first answer**:
Time from the question to the first answer the user sees.
_Avoid_: latency (ambiguous here)

**Time to final answer**:
Time from the question to the answer the user ends up with; equal to time to first answer when there is no correction.

### Evaluation

**Eval case**:
A question paired with gold SQL whose result is the correct answer.

**Gold SQL**:
Hand-written SQL, run on the raw tables, that defines the correct result for an eval case.
_Avoid_: ground truth query, reference SQL

**Execution match**:
Two results containing the same data, ignoring column names and column order.
_Avoid_: exact match, accuracy (accuracy is the rate of execution matches)

**Direct-SQL baseline**:
The comparison arm in which the model writes SQL from table definitions, with no semantic layer.

**Judge**:
A model that grades answers that cannot be execution-matched; it is itself checked against hand labels before it is trusted.
