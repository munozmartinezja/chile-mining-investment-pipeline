from __future__ import annotations

import pandas as pd
import pytest

from cmip.survival import (
    _confidence_frame,
    build_population_exclusions,
    build_population_exclusions_review,
    build_survival_population,
    build_trend_table,
    extract_competing_risk_tables,
    extract_km_tables,
    fit_competing_risks,
    fit_kaplan_meier,
    run_survival_analysis,
)


def test_confidence_frame_orders_lifelines_inverted_aj_labels() -> None:
    confidence = pd.DataFrame(
        {
            "EIA: aprobado_upper_0.95": [0.23],
            "EIA: aprobado_lower_0.95": [0.41],
        },
        index=pd.Index([730.5], name="event_at"),
    )

    result = _confidence_frame(confidence, "ci_lower", "ci_upper")

    assert result.loc[0, "ci_lower"] == pytest.approx(0.23)
    assert result.loc[0, "ci_upper"] == pytest.approx(0.41)


def test_competing_risk_extraction_rejects_interval_not_containing_estimate() -> None:
    class MalformedFitter:
        cumulative_density_ = pd.DataFrame(
            {"DIA: aprobado": [0.5]}, index=pd.Index([10.0], name="event_at")
        )
        confidence_interval_ = pd.DataFrame(
            {
                "DIA: aprobado_upper_0.95": [0.1],
                "DIA: aprobado_lower_0.95": [0.2],
            },
            index=pd.Index([10.0], name="event_at"),
        )

    with pytest.raises(ValueError, match="does not contain cumulative incidence"):
        extract_competing_risk_tables({("DIA", "aprobado"): MalformedFitter()})


def _sea_sample() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "exp_id": [1, 2, 3, 4, 5],
            "exp_nombre": [
                "Proyecto Uno",
                "Proyecto i5",
                "Proyecto Tres",
                "Proyecto Cuatro",
                "Proyecto Cinco",
            ],
            "instrumento": ["DIA", "DIA", "EIA", "EIA", "DIA"],
            "evento": [
                "aprobado",
                "en_tramite",
                "rechazado",
                "aprobado",
                "desistido_o_abandonado",
            ],
            "duracion_dias": [30, 60, 90, 120, 150],
            "fecha_ingreso": pd.to_datetime(["2020-01-01"] * 5),
            "admitido": [True, True, True, False, True],
            "fecha_inconsistente": [False, False, False, False, True],
            "inversion_musd": [1.0, 2.0, 3.0, 4.0, 5.0],
            "region": ["II", "III", "IV", "RM", "VIII"],
            "tipologia": ["i1", "i5", "i3", "i4", "i2"],
        }
    )


def test_build_survival_population_filters_and_encodes_events() -> None:
    result = build_survival_population(_sea_sample())

    assert result["exp_id"].tolist() == [1, 3]
    assert result["approval_event"].tolist() == [1, 0]
    assert result["competing_event"].tolist() == [1, 3]
    assert result["duration_days"].tolist() == [30.0, 90.0]


def test_survival_population_excludes_i5_family_by_tipologia_not_name() -> None:
    """Catch quarry/non-mining rows leaking in through names without keywords."""
    source = pd.DataFrame(
        {
            "exp_id": [1, 2, 3, 4, 5],
            "exp_nombre": [
                "Mina metálica",
                "Ruta 66",
                "Planta sin palabra áridos",
                "Otro proyecto",
                "Proyecto minero válido",
            ],
            "tipologia": ["i1", "i5", "i5.1", "i5.2", "i4"],
            "instrumento": ["DIA"] * 5,
            "evento": ["aprobado"] * 5,
            "duracion_dias": [30] * 5,
            "fecha_ingreso": pd.to_datetime(["2020-01-01"] * 5),
            "admitido": [True] * 5,
            "fecha_inconsistente": [False] * 5,
            "inversion_musd": [1.0] * 5,
            "region": ["II"] * 5,
        }
    )

    assert build_survival_population(source)["exp_id"].tolist() == [1, 5]


def test_survival_population_excludes_explicit_aggregate_name_terms_but_not_quarry() -> None:
    """Catch every approved name term without excluding non-metallic quarries."""
    names = [
        "Extracción de Áridos Pozo Domeyko",
        "Extraccion de aridos para una ruta",
        "Pozo Lastrero Ruta O-50",
        "Explotación de Empréstito Los Lingues",
        "Planta de selección de ripio",
        "Extracción de material para obras viales",
        "Cantera de yeso Santa Rosa",
        "Cantera de caliza El Melón",
        "Proyecto minero válido",
        "Actualización i3 con extracción de áridos",
        "Proyecto i4 Pozo Lastrero",
    ]
    source = pd.DataFrame(
        {
            "exp_id": range(1, len(names) + 1),
            "exp_nombre": names,
            "tipologia": ["i1"] * 9 + ["i3", "i4"],
            "instrumento": ["DIA"] * len(names),
            "evento": ["aprobado"] * len(names),
            "duracion_dias": [30] * len(names),
            "fecha_ingreso": pd.to_datetime(["2020-01-01"] * len(names)),
            "admitido": [True] * len(names),
            "fecha_inconsistente": [False] * len(names),
            "inversion_musd": [1.0] * len(names),
            "region": ["II"] * len(names),
        }
    )

    population = build_survival_population(source)
    exclusions = build_population_exclusions(source)
    review = build_population_exclusions_review(source)

    assert population["exp_id"].tolist() == [5, 7, 8, 9, 10, 11]
    assert exclusions.columns.tolist() == [
        "exp_id",
        "exp_nombre",
        "tipologia",
        "instrumento",
        "motivo",
    ]
    assert exclusions["exp_id"].tolist() == [1, 2, 3, 4, 6]
    assert "cantera" not in " ".join(exclusions["motivo"]).casefold()
    assert "ripio" not in " ".join(exclusions["motivo"]).casefold()
    assert review["exp_id"].tolist() == [10, 11]
    assert review["motivo"].str.startswith("revisión i3/i4: nombre:").all()


class _RecordingKM:
    calls: list[tuple[list[float], list[int], str]] = []

    def fit(self, durations, event_observed, label):  # noqa: ANN001
        self.calls.append((list(durations), list(event_observed), label))
        return self


class _RecordingAJ:
    calls: list[tuple[list[float], list[int], int, str]] = []

    def fit(self, durations, event_observed, event_of_interest, label):  # noqa: ANN001
        self.calls.append((list(durations), list(event_observed), event_of_interest, label))
        return self


def test_km_and_aj_receive_only_the_filtered_population() -> None:
    population = build_survival_population(_sea_sample())
    _RecordingKM.calls.clear()
    _RecordingAJ.calls.clear()

    fit_kaplan_meier(population, fitter_factory=_RecordingKM)
    fit_competing_risks(population, fitter_factory=_RecordingAJ)

    assert _RecordingKM.calls == [([30.0], [1], "DIA"), ([90.0], [0], "EIA")]
    assert all(120.0 not in call[0] and 150.0 not in call[0] for call in _RecordingAJ.calls)
    assert {call[2] for call in _RecordingAJ.calls} == {1, 2, 3, 4}


def test_trend_uses_approved_durations_and_marks_recent_cohorts_incomplete() -> None:
    population = pd.DataFrame(
        {
            "instrumento": ["DIA", "DIA", "DIA", "EIA"],
            "evento": ["aprobado", "rechazado", "aprobado", "aprobado"],
            "fecha_ingreso": pd.to_datetime(
                ["2024-01-01", "2024-02-01", "2025-01-01", "2026-01-01"]
            ),
            "duration_days": [100.0, 10.0, 200.0, 300.0],
        }
    )

    result = build_trend_table(population)

    dia_2024 = result.loc[(result["instrumento"] == "DIA") & (result["anio_ingreso"] == 2024)]
    dia_2025 = result.loc[(result["instrumento"] == "DIA") & (result["anio_ingreso"] == 2025)]
    eia_2026 = result.loc[(result["instrumento"] == "EIA") & (result["anio_ingreso"] == 2026)]
    assert dia_2024["mediana_dias_aprobados"].item() == 100.0
    assert dia_2024["n_aprobados"].item() == 1
    assert not bool(dia_2024["cohorte_incompleta"].item())
    assert bool(dia_2025["cohorte_incompleta"].item())
    assert bool(eia_2026["cohorte_incompleta"].item())


def test_estimators_handle_zero_duration_without_duplicate_curve_keys() -> None:
    population = pd.DataFrame(
        {
            "instrumento": ["DIA", "DIA", "DIA"],
            "duration_days": [0.0, 10.0, 20.0],
            "approval_event": [1, 0, 0],
            "competing_event": [1, 0, 3],
        }
    )

    km_curve, km_summary = extract_km_tables(fit_kaplan_meier(population))
    aj_curve, aj_summary = extract_competing_risk_tables(fit_competing_risks(population))

    assert not km_curve.duplicated(["instrumento", "time_days"]).any()
    assert not aj_curve.duplicated(["instrumento", "outcome", "time_days"]).any()
    assert km_summary.loc[0, "prob_aprobacion_24m"] == pytest.approx(1 / 3)
    at_24_months = aj_summary.loc[aj_summary["horizonte_meses"].eq(24)].set_index(
        "outcome"
    )
    assert at_24_months.loc["aprobado", "incidencia_acumulada"] == pytest.approx(1 / 3)
    assert at_24_months.loc["rechazado", "incidencia_acumulada"] == pytest.approx(2 / 3)


def test_failed_cox_removes_stale_output_and_reports_reason(tmp_path, monkeypatch) -> None:  # noqa: ANN001
    sea_path = tmp_path / "sea.parquet"
    output_dir = tmp_path / "processed"
    results_path = tmp_path / "results.md"
    output_dir.mkdir()
    _sea_sample().to_parquet(sea_path, index=False)
    stale_cox = output_dir / "survival_cox.parquet"
    pd.DataFrame({"stale": [True]}).to_parquet(stale_cox, index=False)

    def fail_cox(population):  # noqa: ANN001
        raise ValueError("singular design matrix")

    monkeypatch.setattr("cmip.survival.fit_cox_model", fail_cox)

    run_survival_analysis(sea_path, output_dir, results_path)

    assert not stale_cox.exists()
    assert "singular design matrix" in results_path.read_text(encoding="utf-8")
    exclusions = pd.read_csv(tmp_path / "population_exclusions.csv")
    assert exclusions.columns.tolist() == [
        "exp_id",
        "exp_nombre",
        "tipologia",
        "instrumento",
        "motivo",
    ]
    assert exclusions["exp_id"].tolist() == [2]
    review = pd.read_csv(tmp_path / "population_exclusions_review.csv")
    assert review.columns.tolist() == exclusions.columns.tolist()
    assert review.empty
