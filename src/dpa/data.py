"""Build the local DuckDB file from the thelook_ecommerce CSV snapshot."""

from __future__ import annotations

from pathlib import Path

import duckdb

# The large `events` table is deliberately left out: no question in the eval set needs it.
TABLES = (
    "distribution_centers",
    "inventory_items",
    "order_items",
    "orders",
    "products",
    "users",
)


def build_db(csv_dir: str | Path, db_path: str | Path, tables: tuple[str, ...] = TABLES) -> dict[str, int]:
    """Load `<csv_dir>/<table>.csv` for each table into a fresh DuckDB file.

    Returns {table: row_count}. Raises FileNotFoundError listing every missing CSV.
    """
    csv_dir, db_path = Path(csv_dir), Path(db_path)
    missing = [t for t in tables if not (csv_dir / f"{t}.csv").exists()]
    if missing:
        raise FileNotFoundError(f"missing CSVs in {csv_dir}: {', '.join(missing)}")
    db_path.parent.mkdir(parents=True, exist_ok=True)
    if db_path.exists():
        db_path.unlink()
    counts = {}
    with duckdb.connect(str(db_path)) as conn:
        for t in tables:
            src = str(csv_dir / f"{t}.csv")
            conn.execute(f"CREATE TABLE {t} AS SELECT * FROM read_csv_auto(?, header=true)", [src])
            counts[t] = conn.execute(f"SELECT count(*) FROM {t}").fetchone()[0]
    return counts
