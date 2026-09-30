from __future__ import annotations

from pathlib import Path

import duckdb
import pytest

from cmip.config import SQL_DIR

SQL_FILES = [
    SQL_DIR / "v001_investment_by_region.sql",
    SQL_DIR / "v002_investment_by_sector.sql",
    SQL_DIR / "v003_investment_by_condicion.sql",
    SQL_DIR / "v004_investment_by_etapa.sql",
    SQL_DIR / "v005_investment_by_pem_inicio.sql",
    SQL_DIR / "v006_top_15_empresas.sql",
]


@pytest.mark.parametrize("sql_path", SQL_FILES, ids=lambda path: path.name)
def test_versioned_query_returns_rows(sql_path: Path, tmp_path: Path, projects) -> None:
    assert sql_path.is_file(), f"missing query: {sql_path.name}"
    database = tmp_path / "queries.duckdb"
    with duckdb.connect(str(database)) as connection:
        connection.register("projects", projects)
        connection.execute("CREATE TABLE cochilco_projects AS SELECT * FROM projects")
        result = connection.execute(sql_path.read_text(encoding="utf-8")).fetchall()
    assert result, f"{sql_path.name} returned no rows"
