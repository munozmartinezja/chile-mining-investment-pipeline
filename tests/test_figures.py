from __future__ import annotations

import pandas as pd
import pytest

from cmip.figures import (
    conclusion_titles,
    make_portfolio_figure,
    make_survival_figures,
    plot_competing_risks,
    plot_km,
    plot_portfolio,
    plot_trend,
)


def test_conclusion_titles_are_derived_from_analysis_values() -> None:
    km = pd.DataFrame(
        {"instrumento": ["DIA", "EIA"], "mediana_km_meses": [8.0, 20.0]}
    )
    competing = pd.DataFrame(
        {
            "instrumento": ["DIA", "EIA"],
            "outcome": ["aprobado", "aprobado"],
            "horizonte_meses": [24, 24],
            "incidencia_acumulada": [0.70, 0.40],
        }
    )
    portfolio = pd.DataFrame(
        {
            "estado_ambiental": ["aprobado", "sin_ingreso_seia", "sin_ingreso_seia"],
            "inversion_musd": [10.0, 30.0, 20.0],
        }
    )

    titles = conclusion_titles(km, competing, portfolio)

    assert "12" in titles["km"]
    assert "30" in titles["competing"]
    assert "sin ingreso SEA" in titles["portfolio"]


def test_all_four_renderers_write_png_files(tmp_path) -> None:  # noqa: ANN001
    pytest.importorskip("matplotlib")
    km = pd.DataFrame(
        {
            "instrumento": ["DIA", "DIA", "EIA", "EIA"],
            "time_days": [0.0, 365.0, 0.0, 365.0],
            "approval_probability": [0.0, 0.8, 0.0, 0.3],
            "approval_ci_lower": [0.0, 0.7, 0.0, 0.2],
            "approval_ci_upper": [0.0, 0.9, 0.0, 0.4],
        }
    )
    competing = pd.DataFrame(
        [
            {
                "instrumento": instrument,
                "outcome": outcome,
                "time_days": time,
                "cumulative_incidence": incidence,
            }
            for instrument in ["DIA", "EIA"]
            for outcome in [
                "aprobado",
                "desistido_o_abandonado",
                "rechazado",
                "termino_anticipado",
            ]
            for time, incidence in [(0.0, 0.0), (365.0, 0.2)]
        ]
    )
    portfolio = pd.DataFrame(
        {
            "estado_ambiental": ["aprobado", "sin_ingreso_seia"],
            "inversion_musd": [20.0, 30.0],
        }
    )
    trend = pd.DataFrame(
        {
            "instrumento": ["DIA", "DIA", "EIA", "EIA"],
            "anio_ingreso": [2024, 2025, 2024, 2025],
            "mediana_dias_aprobados": [200.0, 150.0, 400.0, 300.0],
            "cohorte_incompleta": [False, True, False, True],
        }
    )
    paths = [tmp_path / f"figure_{index}.png" for index in range(4)]

    plot_km(km, "Conclusión KM", paths[0])
    plot_competing_risks(competing, "Conclusión AJ", paths[1])
    plot_portfolio(portfolio, "Conclusión cartera", paths[2])
    plot_trend(trend, paths[3])

    for path in paths:
        assert path.read_bytes().startswith(b"\x89PNG\r\n\x1a\n")


def test_survival_figure_orchestration_does_not_require_portfolio(
    tmp_path, monkeypatch
) -> None:  # noqa: ANN001
    processed = tmp_path / "processed"
    figures = tmp_path / "figures"
    processed.mkdir()
    pd.DataFrame({"instrumento": ["DIA"]}).to_parquet(
        processed / "survival_km.parquet"
    )
    pd.DataFrame({"instrumento": ["DIA", "EIA"], "mediana_km_meses": [8.0, 20.0]}).to_parquet(
        processed / "survival_km_summary.parquet"
    )
    pd.DataFrame({"instrumento": ["DIA"]}).to_parquet(
        processed / "survival_competing_risks.parquet"
    )
    pd.DataFrame(
        {
            "instrumento": ["DIA", "EIA"],
            "outcome": ["aprobado", "aprobado"],
            "horizonte_meses": [24, 24],
            "incidencia_acumulada": [0.7, 0.4],
        }
    ).to_parquet(processed / "survival_competing_risks_summary.parquet")
    pd.DataFrame({"instrumento": ["DIA"]}).to_parquet(
        processed / "survival_trend.parquet"
    )
    monkeypatch.setattr("cmip.figures.plot_km", lambda *args: None)
    monkeypatch.setattr("cmip.figures.plot_competing_risks", lambda *args: None)
    monkeypatch.setattr("cmip.figures.plot_trend", lambda *args: None)

    paths = make_survival_figures(figures, processed)

    assert [path.name for path in paths] == [
        "km_aprobacion_dia_eia.png",
        "incidencia_acumulada_dia_eia.png",
        "duracion_mediana_por_ingreso.png",
    ]


def test_portfolio_figure_orchestration_requires_only_portfolio(
    tmp_path, monkeypatch
) -> None:  # noqa: ANN001
    processed = tmp_path / "processed"
    figures = tmp_path / "figures"
    processed.mkdir()
    pd.DataFrame(
        {"estado_ambiental": ["aprobado"], "inversion_musd": [10.0]}
    ).to_parquet(processed / "cochilco_seia.parquet")
    monkeypatch.setattr("cmip.figures.plot_portfolio", lambda *args: None)

    path = make_portfolio_figure(figures, processed)

    assert path.name == "cartera_estado_ambiental.png"
