from __future__ import annotations

from pathlib import Path

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from cmip.powerbi import (
    POWERBI_SCHEMAS,
    build_powerbi_tables,
    write_powerbi_exports,
)


def _write_sources(tmp_path: Path) -> dict[str, Path]:
    sources = {
        "portfolio_path": tmp_path / "portfolio.parquet",
        "population_path": tmp_path / "population.parquet",
        "km_path": tmp_path / "km.parquet",
        "cif_path": tmp_path / "cif.parquet",
        "trend_path": tmp_path / "trend.parquet",
    }
    pd.DataFrame(
        {
            "project_id": ["p-1", "p-2"],
            "nombre_del_proyecto": ["Proyecto Uno", "Proyecto Dos"],
            "empresa": ["Empresa A", "Empresa B"],
            "mina": ["Mina A", "Mina B"],
            "region": ["Antofagasta", "Coquimbo"],
            "etapa": ["Ejecución", "Prefactibilidad"],
            "condicion": ["Base", "Potencial"],
            "tipo": ["Reposición", "Expansión"],
            "pem_inicio": [2026, 2030],
            "pem_fin": [2027, 2031],
            "inversion_musd": [100.0, 200.0],
            "estado_ambiental": ["aprobado", "sin_expediente_en_estudio"],
            "exp_id_confirmado": pd.Series([10, pd.NA], dtype="Int64"),
            "instrumento": ["EIA", None],
            "fecha_ingreso": [pd.Timestamp("2020-01-02"), pd.NaT],
            "estado": ["Aprobado", None],
            "criterio": ["decision_J", "regla_sin_expediente"],
            "titular_nombre": ["Persona privada", "Otra persona"],
        }
    ).to_parquet(sources["portfolio_path"], index=False)
    pd.DataFrame(
        {
            "exp_id": [10, 20],
            "instrumento": ["EIA", "DIA"],
            "region": ["II", "RM"],
            "tipologia": ["i4", "i2"],
            "inversion_musd": [100.0, 99.9],
            "fecha_ingreso": [pd.Timestamp("2020-01-02"), pd.Timestamp("2021-02-03")],
            "fecha_cierre": [pd.Timestamp("2022-03-04"), pd.NaT],
            "evento": ["aprobado", "en_tramite"],
            "duration_days": [792.0, 365.0],
            "titular_nombre": ["Persona privada", "Otra persona"],
            "exp_nro_rca": [None, None],
        }
    ).to_parquet(sources["population_path"], index=False)
    pd.DataFrame(
        {
            "instrumento": ["DIA", "DIA", "DIA", "EIA", "EIA", "EIA"],
            "time_days": [0.0, 20.0, 50.0, 0.0, 20.0, 50.0],
            "approval_probability": [0.0, 0.2, 0.4, 0.0, 0.1, 0.3],
            "approval_ci_lower": [0.0, 0.1, 0.3, 0.0, 0.05, 0.2],
            "approval_ci_upper": [0.0, 0.3, 0.5, 0.0, 0.15, 0.4],
        }
    ).to_parquet(sources["km_path"], index=False)
    pd.DataFrame(
        {
            "instrumento": ["DIA", "DIA", "DIA", "EIA", "EIA", "EIA"],
            "outcome": ["aprobado"] * 3 + ["rechazado"] * 3,
            "time_days": [0.0, 20.0, 50.0, 0.0, 20.0, 50.0],
            "cumulative_incidence": [0.0, 0.15, 0.25, 0.0, 0.02, 0.04],
        }
    ).to_parquet(sources["cif_path"], index=False)
    pd.DataFrame(
        {
            "instrumento": ["DIA", "EIA"],
            "anio_ingreso": [2020, 2021],
            "mediana_dias_aprobados": [100.0, None],
            "n_aprobados": [5, 0],
            "cohorte_incompleta": [False, True],
        }
    ).to_parquet(sources["trend_path"], index=False)
    return sources


def _claims() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "claim_id": ["cartera_inversion_total", "descartada"],
            "texto_es": ["Inversión total de la cartera", "No publicar"],
            "valor": [300.0, 999.0],
            "unidad": ["MMUS$", "casos"],
            "estado": ["verificada", "rechazada"],
        }
    )


def test_build_powerbi_tables_uses_exact_explicit_schemas(tmp_path: Path) -> None:
    tables = build_powerbi_tables(**_write_sources(tmp_path), claims=_claims())

    assert tables.keys() == POWERBI_SCHEMAS.keys()
    for name, table in tables.items():
        assert table.schema == POWERBI_SCHEMAS[name]
        assert all(not pa.types.is_null(field.type) for field in table.schema)
        assert all(table[column].null_count < table.num_rows for column in table.column_names)
        assert "titular_nombre" not in table.column_names
        assert "exp_nro_rca" not in table.column_names

    assert tables["fact_cartera"].schema.field("fecha_ingreso").type == pa.date32()
    assert tables["fact_expedientes"].schema.field("fecha_ingreso").type == pa.date32()
    assert tables["fact_expedientes"].schema.field("fecha_cierre").type == pa.date32()
    assert tables["fact_cartera"]["macro_zona"].to_pylist() == [
        "Norte Grande",
        "Norte Chico",
    ]
    assert tables["fact_expedientes"]["segmento_inversion"].to_pylist() == [
        "≥100 MMUS$",
        "<100 MMUS$",
    ]
    assert tables["fact_expedientes"]["en_cartera_cochilco"].to_pylist() == [True, False]
    assert tables["kpi_validados"].column("estado").to_pylist() == ["verificada"]
    assert tables["kpi_validados"].column("texto_en").to_pylist() == [
        "Total portfolio investment"
    ]


def test_monthly_curves_are_right_continuous_steps_from_zero_to_72(tmp_path: Path) -> None:
    tables = build_powerbi_tables(**_write_sources(tmp_path), claims=_claims())

    km = tables["agg_km"].to_pandas()
    assert len(km) == 2 * 73
    assert km.groupby("instrumento")["mes"].agg(["min", "max"]).to_dict("index") == {
        "DIA": {"min": 0, "max": 72},
        "EIA": {"min": 0, "max": 72},
    }
    dia = km.loc[km["instrumento"].eq("DIA")].set_index("mes")
    assert dia.loc[0, "prob_aprobado"] == pytest.approx(0.0)
    assert dia.loc[1, "prob_aprobado"] == pytest.approx(0.2)
    assert dia.loc[2, "prob_aprobado"] == pytest.approx(0.4)

    cif = tables["agg_cif"].to_pandas()
    assert len(cif) == 2 * 73
    dia_approved = cif.loc[
        cif["instrumento"].eq("DIA") & cif["desenlace"].eq("aprobado")
    ].set_index("mes")
    assert dia_approved.loc[1, "incidencia"] == pytest.approx(0.15)
    assert dia_approved.loc[2, "incidencia"] == pytest.approx(0.25)


def test_write_powerbi_exports_round_trips_each_parquet(tmp_path: Path) -> None:
    sources = _write_sources(tmp_path)
    output_dir = tmp_path / "powerbi"

    written = write_powerbi_exports(output_dir=output_dir, **sources, claims=_claims())

    for name, expected in written.items():
        path = output_dir / f"{name}.parquet"
        actual = pq.read_table(path)
        assert actual.schema == POWERBI_SCHEMAS[name]
        assert actual.equals(expected)


ROOT = Path(__file__).resolve().parents[1]
REAL_SOURCES = {
    "portfolio_path": ROOT / "data/processed/cochilco_seia.parquet",
    "population_path": ROOT / "data/processed/survival_population.parquet",
    "km_path": ROOT / "data/processed/survival_km.parquet",
    "cif_path": ROOT / "data/processed/survival_competing_risks.parquet",
    "trend_path": ROOT / "data/processed/survival_trend.parquet",
}


@pytest.mark.skipif(
    not all(path.exists() for path in REAL_SOURCES.values()),
    reason="local processed Power BI sources are unavailable",
)
def test_real_powerbi_exports_meet_acceptance_contract(tmp_path: Path) -> None:
    output_dir = tmp_path / "powerbi"

    write_powerbi_exports(output_dir=output_dir, **REAL_SOURCES)

    tables = {path.stem: pq.read_table(path) for path in output_dir.glob("*.parquet")}
    assert set(tables) == set(POWERBI_SCHEMAS)
    for table in tables.values():
        assert all(not pa.types.is_null(field.type) for field in table.schema)
        assert "titular_nombre" not in table.column_names
    assert tables["fact_cartera"].num_rows == 59
    assert pa.compute.sum(tables["fact_cartera"]["inversion_musd"]).as_py() == pytest.approx(
        104_549.2
    )
    assert tables["fact_expedientes"].num_rows == 995
    assert set(tables["kpi_validados"]["estado"].to_pylist()) == {"verificada"}
    assert tables["fact_cartera"].schema.field("fecha_ingreso").type == pa.date32()
    assert tables["fact_expedientes"].schema.field("fecha_ingreso").type == pa.date32()
    assert tables["fact_expedientes"].schema.field("fecha_cierre").type == pa.date32()
