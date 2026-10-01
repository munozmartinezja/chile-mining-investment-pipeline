from __future__ import annotations

from pathlib import Path

import duckdb
import pandas as pd

from cmip.extract.sea import EXPECTED_MINING_STATES, PRIVATE_COLUMNS

PROJECT_ROOT = Path(__file__).resolve().parents[1]
PROJECTS_PATH = PROJECT_ROOT / "data" / "interim" / "sea_projects.parquet"
MINING_PATH = PROJECT_ROOT / "data" / "interim" / "sea_mining.parquet"
DATABASE_PATH = PROJECT_ROOT / "data" / "processed" / "cmip.duckdb"


def test_sea_parquets_exclude_private_columns() -> None:
    for path in (PROJECTS_PATH, MINING_PATH):
        frame = pd.read_parquet(path)
        assert PRIVATE_COLUMNS.isdisjoint(frame.columns)


def test_sea_projects_have_unique_ids_and_valid_durations() -> None:
    projects = pd.read_parquet(PROJECTS_PATH)
    assert projects["exp_id"].is_unique
    assert projects["duracion_dias"].dropna().ge(0).all()
    closed = projects["fecha_cierre"].notna() & projects["fecha_ingreso"].notna()
    assert projects.loc[closed, "fecha_cierre"].ge(projects.loc[closed, "fecha_ingreso"]).all()


def test_sea_mining_state_count_regression() -> None:
    mining = pd.read_parquet(MINING_PATH)
    counts = mining["estado"].value_counts().to_dict()
    evento_counts = mining["evento"].value_counts().to_dict()
    assert len(mining) == 1961
    assert {state: counts.get(state, 0) for state in EXPECTED_MINING_STATES} == (
        EXPECTED_MINING_STATES
    )
    assert sum(
        count for state, count in counts.items() if state not in EXPECTED_MINING_STATES
    ) == 5
    assert evento_counts == {
        "aprobado": 1057,
        "desistido_o_abandonado": 372,
        "no_admitido": 316,
        "termino_anticipado": 122,
        "en_tramite": 58,
        "rechazado": 36,
    }
    post_rca = mining["estado"].isin({"Caducado", "Revocado", "Renuncia RCA"})
    assert post_rca.sum() == 14
    assert mining.loc[post_rca, "estado_post_rca"].equals(mining.loc[post_rca, "estado"])
    assert mining.loc[~post_rca, "estado_post_rca"].isna().all()


def test_duckdb_contains_both_sea_tables() -> None:
    with duckdb.connect(str(DATABASE_PATH), read_only=True) as connection:
        tables = {row[0] for row in connection.execute("SHOW TABLES").fetchall()}
        project_count = connection.execute("SELECT count(*) FROM sea_projects").fetchone()[0]
        mining_count = connection.execute("SELECT count(*) FROM sea_mining").fetchone()[0]
    assert {"sea_projects", "sea_mining"}.issubset(tables)
    assert project_count == 13735
    assert mining_count == 1961
