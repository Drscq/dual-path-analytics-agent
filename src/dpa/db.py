"""DuckDB access: open the local database, run SQL, describe the schema."""

from __future__ import annotations

import time
from pathlib import Path

import duckdb

from dpa.types import QueryResult

DEFAULT_DB = Path("data/thelook.duckdb")


def connect(path: str | Path = DEFAULT_DB, *, read_only: bool = True) -> duckdb.DuckDBPyConnection:
    if str(path) != ":memory:" and not Path(path).exists():
        raise FileNotFoundError(f"{path} not found; run `make data` first")
    return duckdb.connect(str(path), read_only=read_only)


def execute(conn: duckdb.DuckDBPyConnection, sql: str) -> QueryResult:
    start = time.perf_counter()
    cur = conn.execute(sql)
    rows = cur.fetchall()
    elapsed_ms = (time.perf_counter() - start) * 1000
    columns = tuple(d[0] for d in cur.description or ())
    return QueryResult(columns=columns, rows=tuple(tuple(r) for r in rows), elapsed_ms=elapsed_ms)


def schema_ddl(conn: duckdb.DuckDBPyConnection) -> str:
    """CREATE TABLE-style description of every table, for the direct-SQL baseline prompt."""
    tables = [r[0] for r in conn.execute("SELECT table_name FROM information_schema.tables "
                                         "WHERE table_schema = 'main' ORDER BY table_name").fetchall()]
    parts = []
    for t in tables:
        cols = conn.execute(
            "SELECT column_name, data_type FROM information_schema.columns "
            "WHERE table_name = ? ORDER BY ordinal_position", [t]
        ).fetchall()
        body = ",\n".join(f"  {name} {dtype}" for name, dtype in cols)
        parts.append(f"CREATE TABLE {t} (\n{body}\n);")
    return "\n\n".join(parts)
