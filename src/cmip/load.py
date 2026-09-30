"""Build the processed Cochilco dataset and DuckDB database."""

from __future__ import annotations

from pathlib import Path

import duckdb
import pandas as pd

from cmip.config import DATABASE_PATH, INTERIM_DIR, PROCESSED_DIR, RAW_DIR
from cmip.extract.cochilco import extract_annex_tables, write_interim_tables
from cmip.validate import normalize_projects


def _load_frame(
    connection: duckdb.DuckDBPyConnection, table_name: str, frame: pd.DataFrame
) -> None:
    connection.register("_cmip_frame", frame)
    connection.execute(f'CREATE OR REPLACE TABLE "{table_name}" AS SELECT * FROM _cmip_frame')
    connection.unregister("_cmip_frame")


def build_pipeline(
    database_path: Path = DATABASE_PATH,
    interim_dir: Path = INTERIM_DIR,
    processed_dir: Path = PROCESSED_DIR,
    raw_dir: Path = RAW_DIR,
) -> tuple[dict[int, pd.DataFrame], pd.DataFrame]:
    """Extract Annex C, normalize projects, and load all outputs."""
    tables = extract_annex_tables(raw_dir)
    write_interim_tables(tables, interim_dir)
    projects = normalize_projects(tables[1])

    processed_dir.mkdir(parents=True, exist_ok=True)
    projects.to_parquet(processed_dir / "cochilco_projects.parquet", index=False)
    database_path.parent.mkdir(parents=True, exist_ok=True)
    with duckdb.connect(str(database_path)) as connection:
        _load_frame(connection, "cochilco_projects", projects)
        for number, frame in tables.items():
            if number != 1:
                _load_frame(connection, f"cochilco_ctrl_{number:02d}", frame)
    return tables, projects


def main() -> None:
    tables, projects = build_pipeline()
    total = projects["inversion_musd"].sum()
    print(f"Loaded {len(tables)} Annex C tables and {len(projects)} projects ({total:,.1f} MMUSD)")


if __name__ == "__main__":
    main()
