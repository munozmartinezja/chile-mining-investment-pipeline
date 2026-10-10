from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from cmip.validation import (
    bootstrap_eia_high_investment_approval_24m,
    build_claims_register,
    build_sensitivity_table,
)

ROOT = Path(__file__).resolve().parents[1]
PORTFOLIO_PATH = ROOT / "data/processed/cochilco_seia.parquet"
SHARED_EXCEPTIONS_PATH = ROOT / "data/curated/shared_expediente_exceptions.csv"
REQUIRED_DATA = [
    ROOT / "data/processed/cochilco_seia.parquet",
    ROOT / "data/processed/survival_km_summary.parquet",
    ROOT / "data/processed/survival_competing_risks_summary.parquet",
    ROOT / "data/interim/sea_mining.parquet",
]
requires_local_data = pytest.mark.skipif(
    not all(path.exists() for path in REQUIRED_DATA),
    reason="requires local portfolio and SEA analysis parquets",
)


@requires_local_data
def test_minimum_brief_claims_are_independently_verified() -> None:
    register = build_claims_register()

    assert register.columns.tolist() == [
        "claim_id",
        "texto_es",
        "valor",
        "unidad",
        "fuente",
        "calculo",
        "valor_recalculado",
        "diferencia",
        "estado",
        "nota_semantica",
    ]
    assert register["claim_id"].is_unique
    assert register["estado"].eq("verificada").all(), register.loc[
        register["estado"].ne("verificada")
    ].to_dict("records")
    assert register.set_index("claim_id").loc["cartera_inversion_total", "valor"] == pytest.approx(
        104_549.2
    )
    claim_ids = set(register["claim_id"])
    assert {
        "cartera_proyectos_n",
        "sea_poblacion_admitida_n",
        "sea_poblacion_eia_n",
        "estado_sin_expediente_en_estudio_pct",
        "estado_aprobado_pct",
        "estado_sin_expediente_en_ejecucion_n",
        "estado_sin_expediente_en_estudio_n",
        "km_DIA_mediana",
        "km_EIA_mediana",
        "km_DIA_aprobado_24m",
        "km_EIA_aprobado_24m",
        "aj_DIA_aprobado_24m",
        "aj_EIA_aprobado_24m",
        "eia_100m_aj_aprobado_24m_estimacion",
        "eia_100m_aj_aprobado_24m_ic95_inf",
        "eia_100m_aj_aprobado_24m_ic95_sup",
        "eia_en_evaluacion_n",
        "eia_en_evaluacion_inversion",
        "estado_agregado_no_asignable_n",
        "estado_rca_previa_2011_n",
        "estado_pertinencia_n",
        "estado_no_determinado_n",
        "aj_EIA_aprobado_36m",
        "aj_DIA_aprobado_12m",
        "aj_EIA_mes_50pct",
        "aj_EIA_meseta",
        "eia_aprobados_mediana_meses",
        "eia_100m_n",
        "eia_100m_en_riesgo_24m",
        "poblacion_periodo_inicio",
        "poblacion_periodo_fin",
        "cruces_revision_manual_n",
        "cruces_regla_auto_n",
        "headline_piso_pct",
        "headline_techo_pct",
        "aprobado_con_actualizacion_en_calificacion_n",
        "aprobado_con_actualizacion_en_calificacion_inversion",
    }.issubset(claim_ids)
    indexed = register.set_index("claim_id")
    assert indexed.loc["sea_poblacion_admitida_n", "valor"] == 995
    assert indexed.loc["sea_poblacion_eia_n", "valor"] == 124
    assert indexed.loc["eia_100m_n", "valor"] == 81
    assert indexed.loc["poblacion_periodo_inicio", "valor"] == 2011
    assert indexed.loc["poblacion_periodo_fin", "valor"] == 2026
    assert indexed.loc["cruces_revision_manual_n", "valor"] == 59
    assert indexed.loc["cruces_regla_auto_n", "valor"] == 0
    assert indexed.loc["headline_piso_pct", "valor"] == pytest.approx(
        100 * (17_043.0 - 8_000) / 104_549.2
    )
    assert indexed.loc["headline_techo_pct", "valor"] == pytest.approx(
        100 * (17_043.0 + 23_753.9 + 1_300) / 104_549.2
    )
    assert indexed.loc["aprobado_con_actualizacion_en_calificacion_n", "valor"] == 1
    assert indexed.loc[
        "aprobado_con_actualizacion_en_calificacion_inversion", "valor"
    ] == pytest.approx(4_850.9)


@requires_local_data
def test_competing_risk_summary_confidence_interval_contains_estimate() -> None:
    contracts = (
        (
            ROOT / "data/processed/survival_competing_risks.parquet",
            "cumulative_incidence",
        ),
        (
            ROOT / "data/processed/survival_competing_risks_summary.parquet",
            "incidencia_acumulada",
        ),
    )
    for path, estimate_column in contracts:
        frame = pd.read_parquet(path).dropna(subset=["ci_lower", "ci_upper"])
        assert frame["ci_lower"].le(frame[estimate_column]).all(), path
        assert frame[estimate_column].le(frame["ci_upper"]).all(), path


@requires_local_data
def test_sensitivity_reports_requested_population_variants() -> None:
    table = build_sensitivity_table().set_index(["segmento", "instrumento"])
    assert set(table.index.get_level_values("segmento")) == {
        "Principal sin áridos",
        "Con áridos y no mineros i5*",
        "Sin desistimientos <=60 días",
        "Reingresos deduplicados",
    }
    assert table.loc[("Principal sin áridos", "DIA"), "n"] == 871
    assert table.loc[("Principal sin áridos", "EIA"), "n"] == 124
    assert table.loc[("Con áridos y no mineros i5*", "DIA"), "n"] == 1515
    assert table.loc[("Con áridos y no mineros i5*", "EIA"), "n"] == 130


@requires_local_data
def test_bootstrap_is_fixed_seed_and_reports_eia_high_investment_interval() -> None:
    first = bootstrap_eia_high_investment_approval_24m()
    second = bootstrap_eia_high_investment_approval_24m()

    pd.testing.assert_frame_equal(first, second)
    assert first.loc[0, "n"] == 81
    assert first.loc[0, "replicas"] == 2000
    assert first.loc[0, "bootstrap_unidad"] == "familia_reingreso"
    assert first.loc[0, "ic95_inf_pct"] < first.loc[0, "estimacion_pct"]
    assert first.loc[0, "ic95_sup_pct"] > first.loc[0, "estimacion_pct"]


def test_validation_checklist_preserves_40_answers_and_adds_21_pending_automatic_rows() -> None:
    checklist = pd.read_csv(
        ROOT / "docs/validation_checklist.csv", keep_default_na=False
    )

    assert checklist.columns.tolist() == [
        "cochilco_id",
        "cochilco_nombre",
        "empresa",
        "etapa",
        "inversion_musd",
        "candidato_sugerido",
        "exp_id_confirmado",
        "sea_nombre",
        "url_expediente",
        "url_busqueda",
        "pregunta",
        "respuesta_J",
        "fuente_J",
    ]
    assert len(checklist) == 61
    assert checklist["pregunta"].str.contains("corresponde|Existe expediente propio").sum() == 34
    assert checklist["pregunta"].eq("¿N° de RCA vigente que cubre la ejecución?").sum() == 6
    assert checklist["url_busqueda"].str.startswith("https://www.google.com/search?q=").all()
    confirmed = checklist["exp_id_confirmado"].ne("")
    assert checklist.loc[confirmed, "url_expediente"].str.contains(r"id_expediente=\d+&").all()
    assert checklist.loc[~confirmed, "url_expediente"].eq("").all()
    automatic = checklist.loc[
        checklist["pregunta"].eq(
            "¿Confirmas el expediente principal asignado automáticamente?"
        )
    ]
    assert len(automatic) == 21
    assert automatic["respuesta_J"].eq("confirmado").all()
    assert automatic["candidato_sugerido"].str.contains("otros_familia=").all()
    assert automatic["url_expediente"].str.contains(r"id_expediente=\d+&").all()


def test_versioned_validation_checklist_gate_is_complete() -> None:
    path = ROOT / "docs/validation_checklist.csv"
    if not all(source.exists() for source in REQUIRED_DATA):
        pytest.skip("requires local portfolio and SEA analysis parquets")

    checklist = pd.read_csv(path, keep_default_na=False)

    assert len(checklist) == 61
    assert checklist["respuesta_J"].str.strip().ne("").all()
    assert not checklist.duplicated(["cochilco_id", "pregunta"]).any()


@requires_local_data
def test_final_environmental_status_totals_portfolio_investment() -> None:
    portfolio = pd.read_parquet(PORTFOLIO_PATH)

    totals = portfolio.groupby("estado_ambiental")["inversion_musd"].sum()

    assert totals.sum() == pytest.approx(104_549.2, abs=0.05)
    assert {
        "agregado_no_asignable",
        "pertinencia",
        "no_determinado",
    }.issubset(totals.index)

    rt = portfolio.loc[
        portfolio["project_id"].eq("codelco-sulfuros-rt-fase-ii-3")
    ].iloc[0]
    assert rt["exp_id_confirmado"] == 8210090
    assert rt["estado_ambiental"] == "aprobado"
    assert portfolio.loc[
        portfolio["exp_id_confirmado"].eq(8210090), "project_id"
    ].tolist() == ["codelco-sulfuros-rt-fase-ii-3"]


@requires_local_data
def test_no_confirmed_expediente_is_duplicated_outside_curated_exceptions() -> None:
    portfolio = pd.read_parquet(PORTFOLIO_PATH)
    exceptions = pd.read_csv(SHARED_EXCEPTIONS_PATH)
    duplicated = portfolio.loc[
        portfolio["exp_id_confirmado"].notna()
        & portfolio["exp_id_confirmado"].duplicated(keep=False),
        ["project_id", "exp_id_confirmado"],
    ].copy()
    actual = {
        (int(row.exp_id_confirmado), row.project_id)
        for row in duplicated.itertuples(index=False)
    }
    allowed = set(
        zip(
            exceptions["exp_id"].astype(int),
            exceptions["cochilco_id"],
            strict=True,
        )
    )

    assert actual
    assert actual <= allowed
