from __future__ import annotations

from datetime import date
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
    assert projects["fecha_ingreso"].notna().all()
    consistent = ~projects["fecha_inconsistente"]
    assert projects.loc[consistent, "duracion_dias"].notna().all()
    assert projects.loc[consistent, "duracion_dias"].ge(0).all()
    closed = consistent & projects["fecha_cierre"].notna()
    assert projects.loc[closed, "fecha_cierre"].ge(projects.loc[closed, "fecha_ingreso"]).all()


def test_sea_date_coverage_and_bounds() -> None:
    for path in (PROJECTS_PATH, MINING_PATH):
        frame = pd.read_parquet(path)
        assert frame["fecha_ingreso"].notna().all()
        assert frame.loc[~frame["fecha_inconsistente"], "duracion_dias"].notna().all()
        open_cases = frame["fecha_cierre"].isna()
        assert frame.loc[open_cases, "evento"].eq("en_tramite").all()

    projects = pd.read_parquet(PROJECTS_PATH)
    assert projects["fecha_ingreso"].min().date() == date(2011, 1, 3)
    assert projects["fecha_ingreso"].max().date() == date(2026, 8, 28)


def test_sea_date_inconsistency_regression() -> None:
    projects = pd.read_parquet(PROJECTS_PATH)
    mining = pd.read_parquet(MINING_PATH)
    inconsistent = projects.loc[projects["fecha_inconsistente"]]
    inconsistent_mining = mining.loc[mining["fecha_inconsistente"]]

    assert len(inconsistent) == 53
    assert inconsistent["estado"].value_counts().to_dict() == {
        "No Admitido a Tramitación": 49,
        "Desistido": 4,
    }
    assert inconsistent["duracion_dias"].isna().all()
    assert len(inconsistent_mining) == 4
    assert inconsistent_mining["evento"].eq("no_admitido").all()


def test_approved_duration_medians_are_plausible() -> None:
    mining = pd.read_parquet(MINING_PATH)
    approved = mining.loc[mining["evento"].eq("aprobado")]
    medians = approved.groupby("instrumento")["duracion_dias"].median()
    assert medians.index.isin(["DIA", "EIA"]).all()
    assert medians.between(60, 1500).all()
    assert medians["EIA"] > medians["DIA"]


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
