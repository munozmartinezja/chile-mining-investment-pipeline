from __future__ import annotations

from pathlib import Path

import duckdb
import pytest

from cmip.load import build_pipeline


def test_primary_workbook_builds_parquet_and_duckdb_outputs(tmp_path: Path) -> None:
    database = tmp_path / "cmip.duckdb"
    interim = tmp_path / "interim"
    processed = tmp_path / "processed"

    tables, projects = build_pipeline(
        database_path=database,
        interim_dir=interim,
        processed_dir=processed,
    )

    assert len(tables) == 13
    assert len(list(interim.glob("cochilco_tabla_*.parquet"))) == 13
    assert (processed / "cochilco_projects.parquet").stat().st_size > 0
    assert projects["inversion_musd"].sum() == pytest.approx(104_549.2, abs=0.01)
    with duckdb.connect(str(database), read_only=True) as connection:
        table_names = {row[0] for row in connection.execute("SHOW TABLES").fetchall()}
        loaded_total = connection.execute(
            "SELECT SUM(inversion_musd) FROM cochilco_projects"
        ).fetchone()[0]
    assert table_names == {"cochilco_projects"} | {
        f"cochilco_ctrl_{number:02d}" for number in range(2, 14)
    }
    assert loaded_total == pytest.approx(104_549.2, abs=0.01)

