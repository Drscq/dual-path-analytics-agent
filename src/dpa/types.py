"""Shared value types. Pure data, no behaviour. Vocabulary follows CONTEXT.md."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

# --- semantic layer -----------------------------------------------------------------------

DimensionType = Literal["string", "number", "date", "timestamp", "yesno"]
MeasureType = Literal["count", "count_distinct", "sum", "average", "min", "max"]
Relationship = Literal["many_to_one", "one_to_one", "one_to_many"]


@dataclass(frozen=True)
class Dimension:
    name: str
    sql: str  # may reference ${TABLE}
    type: DimensionType = "string"
    primary_key: bool = False
    description: str = ""


@dataclass(frozen=True)
class Measure:
    name: str
    type: MeasureType
    sql: str | None = None  # required for every type except count
    description: str = ""


@dataclass(frozen=True)
class View:
    name: str
    table: str
    dimensions: tuple[Dimension, ...]
    measures: tuple[Measure, ...] = ()


@dataclass(frozen=True)
class Join:
    view: str
    sql_on: str  # references fields as ${view.field}
    relationship: Relationship = "many_to_one"


@dataclass(frozen=True)
class Explore:
    name: str
    base_view: str
    joins: tuple[Join, ...] = ()
    description: str = ""


@dataclass(frozen=True)
class SemanticLayer:
    views: tuple[View, ...]
    explores: tuple[Explore, ...]


# --- semantic query -----------------------------------------------------------------------

FilterOp = Literal["=", "!=", ">", ">=", "<", "<=", "in", "between", "like"]


@dataclass(frozen=True)
class Filter:
    field: str  # "view.field"
    op: FilterOp
    value: Any  # list for "in", [low, high] for "between"


@dataclass(frozen=True)
class Sort:
    field: str
    descending: bool = False


@dataclass(frozen=True)
class SemanticQuery:
    explore: str
    dimensions: tuple[str, ...] = ()
    measures: tuple[str, ...] = ()
    filters: tuple[Filter, ...] = ()
    sorts: tuple[Sort, ...] = ()
    limit: int | None = None


# --- execution ----------------------------------------------------------------------------


@dataclass(frozen=True)
class QueryResult:
    columns: tuple[str, ...]
    rows: tuple[tuple[Any, ...], ...]
    elapsed_ms: float = 0.0


# --- the two paths ------------------------------------------------------------------------


@dataclass(frozen=True)
class FastResult:
    question: str
    query: SemanticQuery
    sql: str
    result: QueryResult
    answer_text: str
    latency_ms: float  # wall time from question to answer_text


IssueKind = Literal[
    "wrong_field", "missing_filter", "wrong_filter", "wrong_aggregation", "wrong_time_window", "other"
]


@dataclass(frozen=True)
class Issue:
    kind: IssueKind
    detail: str


VerdictStatus = Literal["pass", "fail", "error"]


@dataclass(frozen=True)
class Verdict:
    status: VerdictStatus
    issues: tuple[Issue, ...] = ()
    corrected_query: SemanticQuery | None = None
    latency_ms: float = 0.0
    error: str = ""  # set only when status == "error"


# --- orchestration ------------------------------------------------------------------------

Mode = Literal["amend", "hold"]
EventKind = Literal["first", "correction", "caveat"]


@dataclass(frozen=True)
class AnswerEvent:
    kind: EventKind
    text: str
    t_ms: float  # milliseconds since the question arrived


@dataclass
class Transcript:
    question: str
    mode: Mode
    events: list[AnswerEvent] = field(default_factory=list)
    fast: FastResult | None = None
    verdict: Verdict | None = None
    final_query: SemanticQuery | None = None
    final_result: QueryResult | None = None

    @property
    def time_to_first_ms(self) -> float:
        return self.events[0].t_ms

    @property
    def time_to_final_ms(self) -> float:
        """Time at which the answer the user ends up with was shown (first or correction)."""
        shown = [e for e in self.events if e.kind in ("first", "correction")]
        return shown[-1].t_ms
