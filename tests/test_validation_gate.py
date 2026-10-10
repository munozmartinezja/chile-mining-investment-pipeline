from __future__ import annotations

import numpy as np
import pandas as pd
import pytest
from lifelines import AalenJohansenFitter, KaplanMeierFitter

from cmip.validation import (
    _cluster_bootstrap_cif,
    _independent_pending_update_summary,
    build_claims_register,
    build_validation_checklist,
    claim_state,
    finalize_claims_register,
    manual_aalen_johansen,
    manual_kaplan_meier,
    write_validation_checklist,
)


def test_manual_kaplan_meier_matches_lifelines_product_limit() -> None:
    durations = np.array([1.0, 2.0, 2.0, 4.0, 5.0, 7.0])
    observed = np.array([1, 0, 1, 1, 0, 1])

    actual = manual_kaplan_meier(durations, observed)
    expected = KaplanMeierFitter().fit(durations, observed).survival_function_

    assert actual["time_days"].tolist() == expected.index.tolist()
    assert actual["survival_probability"].to_numpy() == pytest.approx(
        expected.iloc[:, 0].to_numpy()
    )
    expected_ci = KaplanMeierFitter().fit(durations, observed).confidence_interval_
    assert actual["survival_ci_lower"].to_numpy() == pytest.approx(
        expected_ci.iloc[:, 0].to_numpy()
    )
    assert actual["survival_ci_upper"].to_numpy() == pytest.approx(
        expected_ci.iloc[:, 1].to_numpy()
    )


def test_manual_aalen_johansen_matches_lifelines_known_competing_risks() -> None:
    durations = np.array([1.0, 2.0, 3.0, 4.0, 5.0, 7.0])
    event_codes = np.array([1, 2, 0, 1, 3, 1])

    actual = manual_aalen_johansen(durations, event_codes, event_of_interest=1)
    expected = AalenJohansenFitter(seed=20261002).fit(
        durations, event_codes, event_of_interest=1
    ).cumulative_density_

    assert actual["time_days"].tolist() == expected.index.tolist()
    assert actual["cumulative_incidence"].to_numpy() == pytest.approx(
        expected.iloc[:, 0].to_numpy()
    )


def test_cluster_bootstrap_does_not_concat_unused_datetime_columns(recwarn) -> None:  # noqa: ANN001
    group = pd.DataFrame(
        {
            "exp_nombre": ["Proyecto A", "Proyecto B"],
            "empresa_nombre": ["Empresa A", "Empresa B"],
            "duration_days": [100.0, 200.0],
            "competing_event": [1, 0],
            "fecha_cierre": pd.to_datetime([None, None]),
        }
    )

    estimates = _cluster_bootstrap_cif(group, replicas=3, seed=20261002)

    assert len(estimates) == 3
    assert not [
        warning
        for warning in recwarn
        if "generic' unit for NumPy timedelta" in str(warning.message)
    ]


def test_pending_update_summary_is_recalculated_by_independent_sql(tmp_path) -> None:  # noqa: ANN001
    checklist_path = tmp_path / "checklist.csv"
    portfolio_path = tmp_path / "portfolio.parquet"
    sea_path = tmp_path / "sea.parquet"
    pd.DataFrame(
        {
            "cochilco_id": ["project-a", "project-b"],
            "fuente_J": [
                "principal: 1111111 | modificaciones: 2222222 | nota: caso A",
                "principal: 3333333 | modificaciones: 4444444 | nota: caso B",
            ],
        }
    ).to_csv(checklist_path, index=False)
    pd.DataFrame(
        {
            "project_id": ["project-a", "project-b"],
            "estado_ambiental": ["aprobado", "en_evaluacion"],
            "inversion_musd": [4_850.9, 900.0],
        }
    ).to_parquet(portfolio_path, index=False)
    pd.DataFrame(
        {
            "exp_id": [2_222_222, 4_444_444],
            "evento": ["en_tramite", "en_tramite"],
        }
    ).to_parquet(sea_path, index=False)

    result = _independent_pending_update_summary(
        checklist_path, portfolio_path, sea_path
    )

    assert result == (1, pytest.approx(4_850.9))


@pytest.mark.parametrize(
    ("value", "recalculated", "tolerance", "expected"),
    [
        (100.0, 100.1, 0.1, "verificada"),
        (100.0, 100.100001, 0.1, "rechazada"),
        (7, 8, 0.0, "rechazada"),
        (7, None, 0.0, "pendiente_J"),
    ],
)
def test_claim_state_rejects_values_beyond_metric_tolerance(
    value: float, recalculated: float | None, tolerance: float, expected: str
) -> None:
    assert claim_state(value, recalculated, tolerance) == expected


def test_claims_register_marks_a_tolerance_breach_as_rejected() -> None:
    rows = [
        {
            "claim_id": "monto",
            "texto_es": "Monto sintético",
            "valor": 100.0,
            "unidad": "MMUS$",
            "fuente": "fixture.parquet",
            "calculo": "suma",
            "valor_recalculado": 100.2,
            "tolerancia": 0.1,
            "nota_semantica": "Misma población y unidad.",
        }
    ]

    register = finalize_claims_register(rows)

    assert register.loc[0, "diferencia"] == pytest.approx(0.2)
    assert register.loc[0, "estado"] == "rechazada"


def test_claims_register_treats_matching_non_reached_medians_as_equal() -> None:
    base = {
        "texto_es": "Mediana no alcanzada",
        "unidad": "meses",
        "fuente": "fixture.parquet",
        "calculo": "producto límite",
        "tolerancia": 0.1,
        "nota_semantica": "No alcanzada dentro del seguimiento.",
    }
    rows = [
        {**base, "claim_id": "same", "valor": np.inf, "valor_recalculado": np.inf},
        {**base, "claim_id": "different", "valor": np.inf, "valor_recalculado": 20.0},
    ]

    register = finalize_claims_register(rows).set_index("claim_id")

    assert register.loc["same", "diferencia"] == 0.0
    assert register.loc["same", "estado"] == "verificada"
    assert np.isinf(register.loc["different", "diferencia"])
    assert register.loc["different", "estado"] == "rechazada"


def test_claims_register_rejects_an_empty_portfolio_source(tmp_path) -> None:  # noqa: ANN001
    empty = tmp_path / "empty.parquet"
    pd.DataFrame(
        columns=[
            "project_id",
            "inversion_musd",
            "estado_ambiental",
            "exp_id_confirmado",
            "etapa",
            "evento",
            "instrumento",
        ]
    ).to_parquet(empty, index=False)

    with pytest.raises(ValueError, match="portfolio.*empty"):
        build_claims_register(empty, empty, empty, empty)


def _synthetic_checklist_sources(tmp_path):  # noqa: ANN001
    portfolio_path = tmp_path / "portfolio.parquet"
    sea_path = tmp_path / "sea.parquet"
    decisions_path = tmp_path / "decisions.csv"
    rows = [
        {
            "project_id": "con-expediente",
            "nombre_del_proyecto": 'Doña "Inés" Proyecto',
            "empresa": "Compañía Pública",
            "etapa": "Factibilidad",
            "inversion_musd": 100.0,
            "exp_id_confirmado": 123.0,
        },
        {
            "project_id": "decision-na",
            "nombre_del_proyecto": "Proyecto sin expediente",
            "empresa": "Empresa Pública",
            "etapa": "Prefactibilidad",
            "inversion_musd": 50.0,
            "exp_id_confirmado": pd.NA,
        },
    ]
    rows.extend(
        {
            "project_id": f"ejecucion-{index}",
            "nombre_del_proyecto": f"Ejecución {index}",
            "empresa": "Codelco",
            "etapa": "Ejecución",
            "inversion_musd": float(index * 10),
            "exp_id_confirmado": pd.NA,
        }
        for index in range(1, 7)
    )
    pd.DataFrame(rows).to_parquet(portfolio_path, index=False)
    pd.DataFrame({"exp_id": [123], "exp_nombre": ["Ficha SEA"]}).to_parquet(
        sea_path, index=False
    )
    pd.DataFrame(
        {
            "cochilco_id": ["con-expediente", "decision-na"],
            "criterio": ["decision_J", "decision_J"],
        }
    ).to_csv(decisions_path, index=False)
    return portfolio_path, sea_path, decisions_path


def test_validation_checklist_builds_human_urls_and_orders_groups(tmp_path) -> None:  # noqa: ANN001
    portfolio, sea, decisions = _synthetic_checklist_sources(tmp_path)

    candidate_review = pd.DataFrame(
        {
            "cochilco_id": ["decision-na"],
            "exp_id": [999],
            "sea_nombre": ["Candidato sugerido"],
            "inversion_ratio": [1.04],
            "score": [98.0],
        }
    )
    checklist = build_validation_checklist(
        portfolio,
        sea,
        decisions,
        checklist_path=None,
        orphans_path=None,
        candidate_review=candidate_review,
    )

    confirmed = checklist.loc[checklist["cochilco_id"].eq("con-expediente")].iloc[0]
    missing = checklist.loc[checklist["cochilco_id"].eq("decision-na")].iloc[0]
    assert confirmed["url_expediente"] == (
        "https://seia.sea.gob.cl/expediente/ficha/fichaPrincipal.php?"
        "id_expediente=123&modo=ficha"
    )
    assert missing["url_expediente"] == ""
    assert missing["candidato_sugerido"] == (
        "999 | Candidato sugerido | inversion_ratio=1.040"
    )
    assert confirmed["url_busqueda"] == (
        "https://www.google.com/search?q=site%3Aseia.sea.gob.cl+"
        "%22Do%C3%B1a+%22In%C3%A9s%22+Proyecto%22"
    )
    assert checklist.columns[:3].tolist() == ["cochilco_id", "cochilco_nombre", "empresa"]
    assert checklist.iloc[:6]["cochilco_id"].tolist() == [
        "ejecucion-6",
        "ejecucion-5",
        "ejecucion-4",
        "ejecucion-3",
        "ejecucion-2",
        "ejecucion-1",
    ]
    assert checklist.iloc[6:]["cochilco_id"].tolist() == [
        "con-expediente",
        "decision-na",
    ]


def test_regenerating_checklist_preserves_j_response_and_source(tmp_path) -> None:  # noqa: ANN001
    portfolio, sea, decisions = _synthetic_checklist_sources(tmp_path)
    checklist_path = tmp_path / "validation_checklist.csv"
    orphans_path = tmp_path / "validation_checklist_orphans.csv"
    existing = build_validation_checklist(
        portfolio, sea, decisions, checklist_path=None, orphans_path=None
    )
    target = existing["cochilco_id"].eq("con-expediente")
    existing.loc[target, "respuesta_J"] = "Sí, corresponde"
    existing.loc[target, "fuente_J"] = "Revisión ficha pública"
    existing.to_csv(checklist_path, index=False)

    regenerated = write_validation_checklist(
        portfolio,
        sea,
        decisions,
        checklist_path=checklist_path,
        orphans_path=orphans_path,
    )

    preserved = regenerated.loc[regenerated["cochilco_id"].eq("con-expediente")].iloc[0]
    assert preserved["respuesta_J"] == "Sí, corresponde"
    assert preserved["fuente_J"] == "Revisión ficha pública"
    persisted = pd.read_csv(checklist_path, keep_default_na=False)
    assert persisted.loc[persisted["cochilco_id"].eq("con-expediente"), "respuesta_J"].item() == (
        "Sí, corresponde"
    )


def test_regenerating_checklist_warns_and_saves_orphan_without_loss(tmp_path) -> None:  # noqa: ANN001
    portfolio, sea, decisions = _synthetic_checklist_sources(tmp_path)
    checklist_path = tmp_path / "validation_checklist.csv"
    orphans_path = tmp_path / "validation_checklist_orphans.csv"
    existing = build_validation_checklist(
        portfolio, sea, decisions, checklist_path=None, orphans_path=None
    )
    orphan = existing.iloc[[0]].copy()
    orphan["cochilco_id"] = "proyecto-huerfano"
    orphan["respuesta_J"] = "Respuesta que no debe perderse"
    pd.concat([existing, orphan], ignore_index=True).to_csv(checklist_path, index=False)

    with pytest.warns(UserWarning, match="proyecto-huerfano"):
        write_validation_checklist(
            portfolio,
            sea,
            decisions,
            checklist_path=checklist_path,
            orphans_path=orphans_path,
        )

    saved = pd.read_csv(orphans_path, keep_default_na=False)
    assert saved["cochilco_id"].tolist() == ["proyecto-huerfano"]
    assert saved["respuesta_J"].tolist() == ["Respuesta que no debe perderse"]
