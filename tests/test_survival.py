from __future__ import annotations

import pandas as pd
import pytest

from cmip.survival import (
    build_survival_population,
    build_trend_table,
    extract_competing_risk_tables,
    extract_km_tables,
    fit_competing_risks,
    fit_kaplan_meier,
    run_survival_analysis,
)


def _sea_sample() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "exp_id": [1, 2, 3, 4, 5],
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
        }
    )


def test_build_survival_population_filters_and_encodes_events() -> None:
    result = build_survival_population(_sea_sample())

    assert result["exp_id"].tolist() == [1, 2, 3]
    assert result["approval_event"].tolist() == [1, 0, 0]
    assert result["competing_event"].tolist() == [1, 0, 3]
    assert result["duration_days"].tolist() == [30.0, 60.0, 90.0]


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

    assert _RecordingKM.calls == [([30.0, 60.0], [1, 0], "DIA"), ([90.0], [0], "EIA")]
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
