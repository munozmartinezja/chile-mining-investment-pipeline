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
            "approval_probability": [0.0, 0.2, 0.4, 0.0, 0.2, 0.5],
            "approval_ci_lower": [0.0, 0.1, 0.3, 0.0, 0.05, 0.2],
            "approval_ci_upper": [0.0, 0.3, 0.5, 0.0, 0.15, 0.4],
        }
    ).to_parquet(sources["km_path"], index=False)
    cif_values = {
        "DIA": {
            "aprobado": [0.0, 0.15, 0.25],
            "desistido_o_abandonado": [0.0, 0.10, 0.20],
            "termino_anticipado": [0.0, 0.05, 0.10],
            "rechazado": [0.0, 0.02, 0.05],
        },
        "EIA": {
            "aprobado": [0.0, 0.20, 0.317436],
            "desistido_o_abandonado": [0.0, 0.10, 0.178864],
            "termino_anticipado": [0.0, 0.04, 0.075000],
            "rechazado": [0.0, 0.005, 0.010456],
        },
    }
    pd.DataFrame(
        [
            {
                "instrumento": instrument,
                "outcome": outcome,
                "time_days": time,
                "cumulative_incidence": incidence,
            }
            for instrument, outcomes in cif_values.items()
            for outcome, incidences in outcomes.items()
            for time, incidence in zip([0.0, 20.0, 50.0], incidences, strict=True)
        ]
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


def test_powerbi_translates_favourable_rca_pending_update_claim(tmp_path: Path) -> None:
    claims = pd.concat(
        [
            _claims(),
            pd.DataFrame(
                {
                    "claim_id": ["aprobado_con_actualizacion_en_calificacion_n"],
                    "texto_es": [
                        "Proyectos con RCA favorable y actualización en calificación"
                    ],
                    "valor": [1.0],
                    "unidad": ["proyectos"],
                    "estado": ["verificada"],
                }
            ),
        ],
        ignore_index=True,
    )

    table = build_powerbi_tables(
        **_write_sources(tmp_path), claims=claims
    )["kpi_validados"].to_pandas().set_index("claim_id")

    assert table.loc[
        "aprobado_con_actualizacion_en_calificacion_n", "texto_en"
    ] == "Projects with a favourable RCA and an update under review"


def test_powerbi_translates_population_count_claims(tmp_path: Path) -> None:
    expected = {
        "sea_poblacion_dia_n": "Admitted DIAs in the survival population",
        "sea_poblacion_evento_aprobado_n": (
            "Filings in the survival population approved by the cut-off"
        ),
        "sea_poblacion_evento_desistido_o_abandonado_n": (
            "Filings in the survival population withdrawn or abandoned by the cut-off"
        ),
        "sea_poblacion_evento_termino_anticipado_n": (
            "Filings in the survival population terminated early by the cut-off"
        ),
        "sea_poblacion_evento_rechazado_n": (
            "Filings in the survival population rejected by the cut-off"
        ),
        "sea_poblacion_evento_en_tramite_n": (
            "Filings in the survival population without an outcome by the cut-off"
        ),
    }
    claims = pd.DataFrame(
        {
            "claim_id": list(expected),
            "texto_es": [f"Conteo {claim_id}" for claim_id in expected],
            "valor": [871, 681, 192, 70, 11, 41],
            "unidad": ["expedientes"] * len(expected),
            "estado": ["verificada"] * len(expected),
        }
    )

    kpis = build_powerbi_tables(
        **_write_sources(tmp_path), claims=claims
    )["kpi_validados"].to_pandas().set_index("claim_id")

    assert kpis["texto_en"].to_dict() == expected


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
    assert len(cif) == 2 * 4 * 73
    dia_approved = cif.loc[
        cif["instrumento"].eq("DIA") & cif["desenlace"].eq("aprobado")
    ].set_index("mes")
    assert dia_approved.loc[1, "incidencia"] == pytest.approx(0.15)
    assert dia_approved.loc[2, "incidencia"] == pytest.approx(0.25)

    gap = tables["agg_brecha_km_aj"].to_pandas()
    assert gap.columns.tolist() == ["instrumento", "mes", "km", "aj", "brecha"]
    assert len(gap) == 2 * 73
    assert gap["brecha"].ge(0).all()
    eia_gap = gap.loc[gap["instrumento"].eq("EIA")].set_index("mes")
    assert eia_gap.loc[24, ["km", "aj", "brecha"]].to_dict() == pytest.approx(
        {"km": 0.5, "aj": 0.317436, "brecha": 0.182564}
    )

    waffle = tables["agg_waffle_24m"].to_pandas()
    assert waffle.columns.tolist() == ["instrumento", "desenlace", "pct", "cuadros"]
    assert waffle["desenlace"].tolist() == [
        "aprobado",
        "desistido_o_abandonado",
        "termino_anticipado",
        "rechazado",
        "en_tramite",
    ] * 2
    assert waffle.groupby("instrumento", sort=False)["cuadros"].sum().tolist() == [100, 100]
    assert waffle.loc[waffle["instrumento"].eq("EIA"), "cuadros"].tolist() == [
        32,
        18,
        7,
        1,
        42,
    ]


def test_write_powerbi_exports_round_trips_each_parquet(tmp_path: Path) -> None:
    sources = _write_sources(tmp_path)
    output_dir = tmp_path / "powerbi"

    written = write_powerbi_exports(output_dir=output_dir, **sources, claims=_claims())

    for name, expected in written.items():
        path = output_dir / f"{name}.parquet"
        actual = pq.read_table(path)
        assert actual.schema == POWERBI_SCHEMAS[name]
        assert actual.equals(expected)


def test_powerbi_kpis_ignore_text_only_audit_claims(tmp_path: Path) -> None:
    sources = _write_sources(tmp_path)
    claims = _claims()
    audit = claims.iloc[[0]].copy()
    audit["claim_id"] = "sea_oficial_fecha_respuesta"
    audit["valor"] = "2026-10-13"
    audit["valor_recalculado"] = "2026-10-13"
    audit["unidad"] = "fecha"
    claims = pd.concat([claims, audit], ignore_index=True)

    tables = build_powerbi_tables(**sources, claims=claims)

    assert "sea_oficial_fecha_respuesta" not in tables["kpi_validados"]["claim_id"].to_pylist()


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
    kpis = tables["kpi_validados"].to_pandas().set_index("claim_id")
    kpi_ids = set(kpis.index)
    assert {
        "km_aj_brecha_EIA_24m_pp",
        "km_aj_brecha_DIA_24m_pp",
        "sin_expediente_inversion_tarapaca",
        "sin_expediente_inversion_atacama",
        "sin_expediente_inversion_valparaiso",
        "sin_expediente_inversion_antofagasta",
        "sin_expediente_mayor_proyecto_inversion",
        "aj_EIA_otros_desenlaces_24m",
        "aj_EIA_sin_desenlace_24m",
    } <= kpi_ids
    facts = tables["fact_expedientes"].to_pandas()
    exported_counts = {
        "sea_poblacion_admitida_n": len(facts),
        "sea_poblacion_dia_n": int(facts["instrumento"].eq("DIA").sum()),
        "sea_poblacion_eia_n": int(facts["instrumento"].eq("EIA").sum()),
        "sea_poblacion_evento_aprobado_n": int(facts["evento"].eq("aprobado").sum()),
        "sea_poblacion_evento_desistido_o_abandonado_n": int(
            facts["evento"].eq("desistido_o_abandonado").sum()
        ),
        "sea_poblacion_evento_termino_anticipado_n": int(
            facts["evento"].eq("termino_anticipado").sum()
        ),
        "sea_poblacion_evento_rechazado_n": int(
            facts["evento"].eq("rechazado").sum()
        ),
        "sea_poblacion_evento_en_tramite_n": int(
            facts["evento"].eq("en_tramite").sum()
        ),
    }
    assert exported_counts == {
        claim_id: int(kpis.loc[claim_id, "valor"]) for claim_id in exported_counts
    }
    assert "sin_expediente_regiones_suma_ok" not in kpi_ids
    gap = tables["agg_brecha_km_aj"].to_pandas()
    assert len(gap) == 146
    assert gap[["km", "aj", "brecha"]].ge(0).all().all()
    assert gap[["km", "aj", "brecha"]].le(1).all().all()
    assert gap.loc[
        gap["instrumento"].eq("EIA") & gap["mes"].eq(24),
        ["km", "aj", "brecha"],
    ].iloc[0].to_dict() == pytest.approx(
        {"km": 0.41568682, "aj": 0.31743611, "brecha": 0.09825071}
    )
    waffle = tables["agg_waffle_24m"].to_pandas()
    assert waffle.loc[waffle["instrumento"].eq("EIA"), "cuadros"].tolist() == [
        32,
        18,
        7,
        1,
        42,
    ]
    assert tables["fact_cartera"].schema.field("fecha_ingreso").type == pa.date32()
    assert tables["fact_expedientes"].schema.field("fecha_ingreso").type == pa.date32()
    assert tables["fact_expedientes"].schema.field("fecha_cierre").type == pa.date32()
