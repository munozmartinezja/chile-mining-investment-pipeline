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
        "clasificacion_ingenua_sin_permiso_pct",
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
    }.issubset(claim_ids)


@requires_local_data
def test_sensitivity_matches_references_except_documented_regex_discrepancy() -> None:
    table = build_sensitivity_table().set_index(["segmento", "instrumento"])
    expected = {
        ("Todos", "DIA"): (1515, 7.7, 66.5),
        ("Todos", "EIA"): (130, 28.8, 31.1),
        (">=100 MMUS$", "DIA"): (97, 8.4, 78.1),
        (">=100 MMUS$", "EIA"): (83, 25.6, 38.4),
        ("<100 MMUS$", "EIA"): (47, 35.8, 18.1),
    }
    for key, (n, median, incidence) in expected.items():
        assert table.loc[key, "n"] == n
        assert table.loc[key, "mediana_km_meses"] == pytest.approx(median, abs=0.05)
        assert table.loc[key, "incidencia_aprobacion_24m_pct"] == pytest.approx(
            incidence, abs=0.05
        )

    # The documented regex removes every expediente whose normalized name contains
    # the whole word árido(s) or cantera(s): seven EIA rows, not the six implied by
    # the supplied reference table.
    assert table.loc[("Sin áridos/canteras", "EIA"), "n"] == 123
    assert table.loc[
        ("Sin áridos/canteras", "EIA"), "incidencia_aprobacion_24m_pct"
    ] == pytest.approx(32.5, abs=0.05)


@requires_local_data
def test_bootstrap_is_fixed_seed_and_reports_eia_high_investment_interval() -> None:
    first = bootstrap_eia_high_investment_approval_24m()
    second = bootstrap_eia_high_investment_approval_24m()

    pd.testing.assert_frame_equal(first, second)
    assert first.loc[0, "n"] == 83
    assert first.loc[0, "replicas"] == 1000
    assert first.loc[0, "estimacion_pct"] == pytest.approx(38.4, abs=0.05)
    assert first.loc[0, "ic95_inf_pct"] < first.loc[0, "estimacion_pct"]
    assert first.loc[0, "ic95_sup_pct"] > first.loc[0, "estimacion_pct"]


def test_validation_checklist_is_the_complete_immutable_review_source() -> None:
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
    assert len(checklist) == 40
    assert checklist["pregunta"].str.contains("corresponde|Existe expediente propio").sum() == 34
    assert checklist["pregunta"].eq("¿N° de RCA vigente que cubre la ejecución?").sum() == 6
    assert checklist["url_busqueda"].str.startswith("https://www.google.com/search?q=").all()
    confirmed = checklist["exp_id_confirmado"].ne("")
    assert checklist.loc[confirmed, "url_expediente"].str.contains(r"id_expediente=\d+&").all()
    assert checklist.loc[~confirmed, "url_expediente"].eq("").all()


def test_versioned_validation_checklist_has_40_rows() -> None:
    path = ROOT / "docs/validation_checklist.csv"
    if not all(source.exists() for source in REQUIRED_DATA):
        pytest.skip("requires local portfolio and SEA analysis parquets")

    checklist = pd.read_csv(path, keep_default_na=False)

    assert len(checklist) == 40
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
