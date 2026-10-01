"""Render the survival and environmental-portfolio figures."""

from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd

from cmip.config import PROCESSED_DIR, PROJECT_ROOT
from cmip.survival import (
    AJ_PATH,
    AJ_SUMMARY_PATH,
    DAYS_PER_MONTH,
    EVENT_LABELS,
    KM_PATH,
    KM_SUMMARY_PATH,
    TREND_PATH,
)

FIGURES_DIR = PROJECT_ROOT / "docs" / "figures"
PORTFOLIO_PATH = PROCESSED_DIR / "cochilco_seia.parquet"
SOURCE = "Fuente: Cochilco (dic-2025), SEA (corte 30-09-2026). Elaboración propia."
COLORS = {
    "DIA": "#176B87",
    "EIA": "#D97706",
    "aprobado": "#2E7D5B",
    "desistido_o_abandonado": "#B26A00",
    "rechazado": "#A63D40",
    "termino_anticipado": "#6B7280",
    "en_evaluacion": "#3B82F6",
    "sin_ingreso_seia": "#94A3B8",
    "desistido_o_rechazado": "#B45309",
    "otro": "#64748B",
}


def _pretty_status(value: str) -> str:
    labels = {
        "aprobado": "Aprobado",
        "en_evaluacion": "En evaluación",
        "sin_ingreso_seia": "Sin ingreso SEA",
        "desistido_o_rechazado": "Desistido o rechazado",
        "otro": "Otro",
    }
    return labels.get(value, value.replace("_", " ").capitalize())


def conclusion_titles(
    km_summary: pd.DataFrame,
    competing_summary: pd.DataFrame,
    portfolio: pd.DataFrame,
) -> dict[str, str]:
    """Derive concise conclusion-led titles from the analysis tables."""
    medians = km_summary.set_index("instrumento")["mediana_km_meses"]
    km_difference = medians.get("EIA", float("nan")) - medians.get("DIA", float("nan"))
    km_title = f"EIA tarda {km_difference:.0f} meses más que DIA en alcanzar la mediana KM"

    approval_24 = competing_summary.loc[
        competing_summary["horizonte_meses"].eq(24)
        & competing_summary["outcome"].eq("aprobado")
    ].set_index("instrumento")["incidencia_acumulada"]
    difference_pp = 100 * (approval_24.get("DIA", 0) - approval_24.get("EIA", 0))
    leader = "DIA" if difference_pp >= 0 else "EIA"
    competing_title = (
        f"{leader} alcanza {abs(difference_pp):.0f} pp más de aprobación a 24 meses"
    )

    portfolio_title = _portfolio_title(portfolio)
    return {"km": km_title, "competing": competing_title, "portfolio": portfolio_title}


def _portfolio_title(portfolio: pd.DataFrame) -> str:
    distribution = portfolio.groupby("estado_ambiental")["inversion_musd"].sum()
    largest = str(distribution.idxmax())
    pretty_largest = _pretty_status(largest)
    return (
        "La mayor inversión de cartera está "
        f"{pretty_largest[0].lower()}{pretty_largest[1:]}"
    )


def _pyplot():
    try:
        import matplotlib

        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except ModuleNotFoundError as error:  # pragma: no cover - environment dependent
        raise RuntimeError("matplotlib is required; run `make setup`") from error
    plt.rcParams.update(
        {
            "font.family": "DejaVu Sans",
            "font.size": 9,
            "axes.titleweight": "bold",
            "axes.spines.top": False,
            "axes.spines.right": False,
            "axes.grid": True,
            "grid.alpha": 0.18,
            "figure.facecolor": "white",
        }
    )
    return plt


def _finish(fig, path: Path) -> None:  # noqa: ANN001
    fig.text(0.01, 0.01, SOURCE, fontsize=7, color="#4B5563")
    fig.savefig(path, dpi=150, bbox_inches="tight", facecolor="white")


def plot_km(curve: pd.DataFrame, title: str, path: Path) -> None:
    plt = _pyplot()
    fig, ax = plt.subplots(figsize=(8, 4.8))
    for instrument, group in curve.groupby("instrumento", sort=True):
        group = group.sort_values("time_days")
        months = group["time_days"].to_numpy() / DAYS_PER_MONTH
        color = COLORS.get(str(instrument), "#334155")
        ax.step(
            months,
            group["approval_probability"].to_numpy(),
            where="post",
            label=str(instrument),
            color=color,
            linewidth=2,
        )
        ax.fill_between(
            months,
            group["approval_ci_lower"].to_numpy(),
            group["approval_ci_upper"].to_numpy(),
            step="post",
            alpha=0.14,
            color=color,
        )
    ax.set(title=title, xlabel="Meses desde el ingreso", ylabel="Probabilidad KM de aprobación")
    ax.set_ylim(0, 1)
    ax.legend(frameon=False)
    _finish(fig, path)
    plt.close(fig)


def plot_competing_risks(curve: pd.DataFrame, title: str, path: Path) -> None:
    plt = _pyplot()
    fig, axes = plt.subplots(1, 2, figsize=(10.5, 4.8), sharex=True, sharey=True)
    for ax, instrument in zip(axes, ["DIA", "EIA"], strict=True):
        subset = curve.loc[curve["instrumento"].eq(instrument)]
        for outcome, group in subset.groupby("outcome", sort=False):
            group = group.sort_values("time_days")
            ax.step(
                group["time_days"] / DAYS_PER_MONTH,
                group["cumulative_incidence"],
                where="post",
                label=EVENT_LABELS[str(outcome)],
                color=COLORS[str(outcome)],
                linewidth=1.8,
            )
        ax.set_title(instrument)
        ax.set_xlabel("Meses desde el ingreso")
        ax.set_ylim(0, 1)
    axes[0].set_ylabel("Incidencia acumulada")
    axes[1].legend(frameon=False, fontsize=8)
    fig.suptitle(title, fontweight="bold", y=0.98)
    _finish(fig, path)
    plt.close(fig)


def plot_portfolio(portfolio: pd.DataFrame, title: str, path: Path) -> None:
    plt = _pyplot()
    distribution = (
        portfolio.groupby("estado_ambiental", as_index=False)["inversion_musd"]
        .sum()
        .sort_values("inversion_musd")
    )
    labels = distribution["estado_ambiental"].map(_pretty_status)
    colors = distribution["estado_ambiental"].map(COLORS)
    fig, ax = plt.subplots(figsize=(8, 4.8))
    bars = ax.barh(labels, distribution["inversion_musd"], color=colors)
    ax.bar_label(bars, fmt="%.0f", padding=3, fontsize=8)
    ax.set(title=title, xlabel="Inversión (MMUS$)", ylabel="")
    _finish(fig, path)
    plt.close(fig)


def plot_trend(trend: pd.DataFrame, path: Path) -> None:
    plt = _pyplot()
    complete = trend.loc[~trend["cohorte_incompleta"] & trend["mediana_dias_aprobados"].notna()]
    peak = complete.loc[complete["mediana_dias_aprobados"].idxmax()]
    title = (
        f"{peak['instrumento']} registra el máximo anual: "
        f"{peak['mediana_dias_aprobados'] / DAYS_PER_MONTH:.0f} meses en "
        f"{int(peak['anio_ingreso'])}"
    )
    fig, ax = plt.subplots(figsize=(9, 4.8))
    for instrument, group in trend.groupby("instrumento", sort=True):
        ax.plot(
            group["anio_ingreso"],
            group["mediana_dias_aprobados"] / DAYS_PER_MONTH,
            marker="o",
            markersize=3.5,
            linewidth=1.8,
            label=str(instrument),
            color=COLORS.get(str(instrument), "#334155"),
        )
    ax.axvspan(2024.5, 2026.5, color="#CBD5E1", alpha=0.35)
    ax.text(
        2025.5,
        ax.get_ylim()[1] * 0.94,
        "Cohortes\nincompletas",
        ha="center",
        va="top",
        fontsize=8,
    )
    ax.set(
        title=title,
        xlabel="Año de ingreso",
        ylabel="Mediana observada entre aprobados (meses)",
        xticks=range(2011, 2027),
    )
    ax.tick_params(axis="x", rotation=45)
    ax.legend(frameon=False)
    _finish(fig, path)
    plt.close(fig)


def make_survival_figures(
    output_dir: Path = FIGURES_DIR,
    processed_dir: Path = PROCESSED_DIR,
) -> list[Path]:
    """Render SEA-only KM, competing-risk, and duration-trend figures."""
    km = pd.read_parquet(processed_dir / KM_PATH.name)
    km_summary = pd.read_parquet(processed_dir / KM_SUMMARY_PATH.name)
    competing = pd.read_parquet(processed_dir / AJ_PATH.name)
    competing_summary = pd.read_parquet(processed_dir / AJ_SUMMARY_PATH.name)
    trend = pd.read_parquet(processed_dir / TREND_PATH.name)
    medians = km_summary.set_index("instrumento")["mediana_km_meses"]
    km_difference = medians.get("EIA", float("nan")) - medians.get(
        "DIA", float("nan")
    )
    km_title = (
        f"EIA tarda {km_difference:.0f} meses más que DIA en alcanzar la mediana KM"
    )
    approval_24 = competing_summary.loc[
        competing_summary["horizonte_meses"].eq(24)
        & competing_summary["outcome"].eq("aprobado")
    ].set_index("instrumento")["incidencia_acumulada"]
    difference_pp = 100 * (approval_24.get("DIA", 0) - approval_24.get("EIA", 0))
    leader = "DIA" if difference_pp >= 0 else "EIA"
    competing_title = (
        f"{leader} alcanza {abs(difference_pp):.0f} pp más de aprobación a 24 meses"
    )
    output_dir.mkdir(parents=True, exist_ok=True)
    paths = [
        output_dir / "km_aprobacion_dia_eia.png",
        output_dir / "incidencia_acumulada_dia_eia.png",
        output_dir / "duracion_mediana_por_ingreso.png",
    ]
    plot_km(km, km_title, paths[0])
    plot_competing_risks(competing, competing_title, paths[1])
    plot_trend(trend, paths[2])
    return paths


def make_portfolio_figure(
    output_dir: Path = FIGURES_DIR,
    processed_dir: Path = PROCESSED_DIR,
) -> Path:
    """Render the portfolio environmental-status figure."""
    portfolio = pd.read_parquet(processed_dir / PORTFOLIO_PATH.name)
    output_dir.mkdir(parents=True, exist_ok=True)
    path = output_dir / "cartera_estado_ambiental.png"
    plot_portfolio(portfolio, _portfolio_title(portfolio), path)
    return path


def make_figures(
    output_dir: Path = FIGURES_DIR,
    processed_dir: Path = PROCESSED_DIR,
) -> list[Path]:
    """Render all four requested figures."""
    return make_survival_figures(output_dir, processed_dir) + [
        make_portfolio_figure(output_dir, processed_dir)
    ]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "scope", nargs="?", choices=["all", "survival", "portfolio"], default="all"
    )
    scope = parser.parse_args().scope
    if scope == "survival":
        paths = make_survival_figures()
    elif scope == "portfolio":
        paths = [make_portfolio_figure()]
    else:
        paths = make_figures()
    print("Wrote figures:")
    for path in paths:
        print(path)


if __name__ == "__main__":
    main()
