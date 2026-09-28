"""Download the thelook_ecommerce CSV snapshot from Kaggle and build data/thelook.duckdb.

Usage:  python scripts/download_data.py [--csv-dir DIR]

Pass --csv-dir to skip the download and build from CSVs you already have.
If Kaggle asks for credentials, put your token at ~/.kaggle/kaggle.json (Kaggle -> Settings ->
API -> Create New Token); this script never reads or prints it.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from dpa.data import TABLES, build_db

KAGGLE_DATASET = "mustafakeser4/looker-ecommerce-bigquery-dataset"
DB_PATH = Path("data/thelook.duckdb")


def find_csv_dir(root: Path) -> Path:
    """The Kaggle archive may nest the CSVs; return the directory holding orders.csv."""
    hits = sorted(root.rglob("orders.csv"))
    if not hits:
        raise FileNotFoundError(f"no orders.csv under {root}")
    return hits[0].parent


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--csv-dir", type=Path)
    args = ap.parse_args()

    if args.csv_dir:
        csv_dir = args.csv_dir
    else:
        import kagglehub

        csv_dir = find_csv_dir(Path(kagglehub.dataset_download(KAGGLE_DATASET)))
    counts = build_db(csv_dir, DB_PATH, TABLES)
    print(f"built {DB_PATH} from {csv_dir}")
    for table, n in counts.items():
        print(f"  {table:22s} {n:>9,d} rows")


if __name__ == "__main__":
    main()
