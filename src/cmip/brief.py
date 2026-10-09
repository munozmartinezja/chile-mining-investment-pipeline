"""Build the bilingual one-page executive brief from verified claims only."""

# ruff: noqa: E501  # Approved publication copy is kept as literal, auditable lines.

from __future__ import annotations

import argparse
import textwrap
from pathlib import Path
from xml.sax.saxutils import escape

import matplotlib
import pandas as pd

from cmip.config import AUTHOR_LINE, PROJECT_ROOT
from cmip.survival import AJ_PATH, DAYS_PER_MONTH, KM_PATH
from cmip.validation import CLAIM_COLUMNS, build_claims_register

matplotlib.use("Agg")

BRIEF_DIR = PROJECT_ROOT / "docs" / "brief"
FIGURES_DIR = PROJECT_ROOT / "docs" / "figures"
PORTFOLIO_FIGURE_PATHS = {
    lang: FIGURES_DIR / f"cartera_estado_ambiental_brief_{lang}.png"
    for lang in ("es", "en")
}
INCIDENCE_FIGURE_PATHS = {
    lang: FIGURES_DIR / f"incidencia_brief_{lang}.png" for lang in ("es", "en")
}
CLAIMS_MAP_PATH = BRIEF_DIR / "claims_map.csv"

TEXTS = {
    "es": {
        "headline": "{share}% de la inversión minera 2025–2034 no tiene expediente SEIA identificado",
        "subtitle": "{amount} MMUS$ en {n} proyectos, todos en etapa de estudio · corte SEA {fecha_datos}",
        "km_title": "Aprobación acumulada de EIA",
        "km_body": "{aj24}% a 24 meses\n{aj36}% a 36 meses{m50}",
        "bootstrap_title": "EIA ≥100 MMUS$ aprobados a 24 meses",
        "bootstrap_body": "{center}% (IC95% {lo}–{hi}) · n={n}",
        "evaluation_title": "En calificación al corte SEA",
        "evaluation_body": "{amount} MMUS$ · {n} proyectos",
        "approved_title": "Con RCA favorable",
        "approved_body": "{amount} MMUS$ · {share}% de la cartera",
        "portfolio_title": "Proyectos en estudio sin expediente identificado: {share}% de la inversión",
        "incidence_title": "Ignorar desistimientos y rechazos (Kaplan–Meier) sobrestima la aprobación",
        "months_axis": "Meses desde el ingreso",
        "approval_axis": "Probabilidad de aprobación",
        "km_legend": "Kaplan-Meier",
        "aj_legend": "Aalen-Johansen",
        "implications": "Implicancias para contratistas",
        "bullets": (
            "Estos ~{amount_round} MMUS$ aún deben ingresar al SEIA antes de construir. A 24 meses de su ingreso, {aj24}% de los EIA está aprobado.",
            "Para EIA ≥100 MMUS$ estimamos {center}% aprobado a 24 meses (IC95% {lo}–{hi}%): conviene planificar con holgura de permisos sobre las fechas de puesta en marcha de Cochilco.",
            "La cifra puede ser mayor: {n_agg} filas agregadas de Codelco ({amount_agg} MMUS$) no permiten asignar un expediente único.",
        ),
        "method_title": "Método y alcance",
        "method_lines": (
            "Fuentes: Cochilco, Cartera de Proyectos de Inversión Minera 2025–2034 (Anexo C, dic-2025). SEA: descarga 30-09-2026, último registro {fecha_datos}.",
            "Población: {population} expedientes mineros admitidos, ingresados entre {p_ini} y {p_fin}; excluye áridos. Kaplan–Meier y Aalen–Johansen; meses = días/30,44.",
            "Cartera: expediente principal por proyecto; las modificaciones no cuentan como cruce. Tiempos: cada expediente, incluidos reingresos.",
            "{n_manual} de {n_total} cruces revisados ficha por ficha. Sensibilidad del titular: {piso}%–{techo}% según 2 clasificaciones y las filas agregadas.",
            "Cada cifra se recalcula por una segunda vía (SQL y estimadores propios) y se verifica con tests automáticos; código y datos en el repositorio.",
        ),
    },
    "en": {
        "headline": "{share}% of 2025–2034 mining investment has no identified SEIA filing",
        "subtitle": "US${amount}m across {n} projects, all at study stage · SEA data to {fecha_datos}",
        "km_title": "Cumulative EIA approval",
        "km_body": "{aj24}% at 24 months\n{aj36}% at 36 months{m50}",
        "bootstrap_title": "EIAs ≥US$100m approved at 24 months",
        "bootstrap_body": "{center}% (95% CI {lo}–{hi}) · n={n}",
        "evaluation_title": "Under review at SEA cut-off",
        "evaluation_body": "US${amount}m · {n} projects",
        "approved_title": "Favourable RCA",
        "approved_body": "US${amount}m · {share}% of portfolio",
        "portfolio_title": "Study-stage projects with no identified filing: {share}% of investment",
        "incidence_title": "Ignoring withdrawals and rejections (Kaplan–Meier) overstates approval",
        "months_axis": "Months since filing",
        "approval_axis": "Approval probability",
        "km_legend": "Kaplan-Meier",
        "aj_legend": "Aalen-Johansen",
        "implications": "Implications for contractors",
        "bullets": (
            "These ~US${amount_round}m still need to enter SEIA before construction. At 24 months after filing, {aj24}% of EIAs are approved.",
            "For EIAs ≥US$100m, we estimate {center}% approved at 24 months (95% CI {lo}–{hi}%): permit schedules should include contingency beyond Cochilco's commissioning dates.",
            "The figure may be higher: {n_agg} aggregate Codelco rows (US${amount_agg}m) cannot be assigned a unique filing.",
        ),
        "method_title": "Method and scope",
        "method_lines": (
            "Sources: Cochilco, 2025–2034 Mining Investment Project Portfolio (Annex C, Dec-2025). SEA: downloaded 30-09-2026; latest record {fecha_datos}.",
            "Population: {population} admitted mining filings entered between {p_ini} and {p_fin}; excludes sand-and-gravel (áridos) filings. Kaplan–Meier and Aalen–Johansen; months = days/30.44.",
            "Portfolio: one principal filing per project; modifications do not count as a match. Times: each filing, including re-entries.",
            "{n_manual} of {n_total} matches reviewed filing by filing. Headline sensitivity: {piso}%–{techo}% under 2 classifications and aggregate rows.",
            "Each figure is recomputed by a second route (SQL and hand-written estimators) and checked by automated tests; code and data in the repository.",
        ),
    },
}

BRIEF_CLAIM_IDS = (
    "cartera_inversion_total",
    "cartera_proyectos_n",
    "sea_poblacion_admitida_n",
    "estado_sin_expediente_en_estudio_inversion",
    "estado_sin_expediente_en_estudio_n",
    "estado_sin_expediente_en_estudio_pct",
    "estado_aprobado_inversion",
    "estado_aprobado_pct",
    "estado_en_evaluacion_inversion",
    "estado_en_evaluacion_n",
    "estado_desistido_rechazado_o_no_calificado_inversion",
    "estado_agregado_no_asignable_inversion",
    "estado_agregado_no_asignable_n",
    "estado_pertinencia_inversion",
    "estado_no_determinado_inversion",
    "km_DIA_aprobado_24m",
    "km_EIA_aprobado_24m",
    "aj_DIA_aprobado_24m",
    "aj_EIA_aprobado_24m",
    "aj_EIA_aprobado_36m",
    "aj_EIA_mes_50pct",
    "eia_100m_aj_aprobado_24m_estimacion",
    "eia_100m_aj_aprobado_24m_ic95_inf",
    "eia_100m_aj_aprobado_24m_ic95_sup",
    "eia_100m_n",
    "poblacion_periodo_inicio",
    "poblacion_periodo_fin",
    "cruces_revision_manual_n",
    "cruces_regla_auto_n",
    "headline_piso_pct",
    "headline_techo_pct",
    "sea_fecha_datos_dia",
    "sea_fecha_datos_mes",
    "sea_fecha_datos_anio",
    "headline_amount_round_mmusd",
    "confidence_level_pct",
    "aj_threshold_pct",
)


def compute_brief_metrics(register: pd.DataFrame | None = None) -> pd.DataFrame:
    """Return exactly the verified claims permitted to appear in the brief."""
    claims = build_claims_register() if register is None else register.copy()
    if claims["claim_id"].duplicated().any():
        raise ValueError("Claims register contains duplicate claim_id values")
    indexed = claims.set_index("claim_id", drop=False)
    missing = [claim_id for claim_id in BRIEF_CLAIM_IDS if claim_id not in indexed.index]
    if missing:
        raise ValueError(f"Claims register is missing brief claims: {missing}")
    metrics = indexed.loc[list(BRIEF_CLAIM_IDS)].reset_index(drop=True)
    invalid = metrics.loc[metrics["estado"].ne("verificada"), ["claim_id", "estado"]]
    if not invalid.empty:
        details = ", ".join(
            f"{row.claim_id}={row.estado}" for row in invalid.itertuples(index=False)
        )
        raise ValueError(f"Brief claims must be verificada: {details}")
    return metrics


def format_number(value: float | int, decimals: int, lang: str) -> str:
    """Format one number with Spanish or English separators."""
    if lang not in {"es", "en"}:
        raise ValueError(f"Unsupported language: {lang}")
    rendered = f"{float(value):,.{decimals}f}"
    if lang == "es":
        rendered = rendered.translate(str.maketrans({",": ".", ".": ","}))
    return rendered


def _metric_values(metrics: pd.DataFrame) -> dict[str, float]:
    missing_columns = set(CLAIM_COLUMNS) - set(metrics.columns)
    if missing_columns:
        raise ValueError(f"Brief metrics missing register columns: {sorted(missing_columns)}")
    invalid = metrics.loc[metrics["estado"].ne("verificada"), ["claim_id", "estado"]]
    if not invalid.empty:
        raise ValueError(f"Brief received unverified metrics: {invalid.to_dict('records')}")
    return metrics.set_index("claim_id")["valor"].astype(float).to_dict()


def _brief_copy(metrics: pd.DataFrame, lang: str) -> dict[str, object]:
    if lang not in TEXTS:
        raise ValueError(f"Unsupported language: {lang}")
    values = _metric_values(metrics)
    text = TEXTS[lang]

    def number(claim_id: str, decimals: int = 0) -> str:
        return format_number(values[claim_id], decimals, lang)

    date_separator = "-"
    data_date = date_separator.join(
        (
            number("sea_fecha_datos_dia"),
            number("sea_fecha_datos_mes").zfill(2),
            str(int(values["sea_fecha_datos_anio"])),
        )
    )
    month_50 = values["aj_EIA_mes_50pct"]
    if pd.isna(month_50):
        m50 = ""
    elif lang == "es":
        m50 = f"\n50% a ~{number('aj_EIA_mes_50pct', 0)} meses"
    else:
        m50 = f"\n50% at ~{number('aj_EIA_mes_50pct', 0)} months"

    copy: dict[str, object] = {
        "headline": text["headline"].format(
            share=number("estado_sin_expediente_en_estudio_pct", 1)
        ),
        "subtitle": text["subtitle"].format(
            amount=number("estado_sin_expediente_en_estudio_inversion"),
            n=number("estado_sin_expediente_en_estudio_n"),
            fecha_datos=data_date,
        ),
        "km_title": text["km_title"],
        "km_body": text["km_body"].format(
            aj24=number("aj_EIA_aprobado_24m", 1),
            aj36=number("aj_EIA_aprobado_36m", 1),
            m50=m50,
        ),
        "bootstrap_title": text["bootstrap_title"],
        "bootstrap_body": text["bootstrap_body"].format(
            lo=number("eia_100m_aj_aprobado_24m_ic95_inf", 1),
            hi=number("eia_100m_aj_aprobado_24m_ic95_sup", 1),
            center=number("eia_100m_aj_aprobado_24m_estimacion", 1),
            n=number("eia_100m_n"),
        ),
        "evaluation_title": text["evaluation_title"],
        "evaluation_body": text["evaluation_body"].format(
            amount=number("estado_en_evaluacion_inversion"),
            n=number("estado_en_evaluacion_n"),
        ),
        "approved_title": text["approved_title"],
        "approved_body": text["approved_body"].format(
            amount=number("estado_aprobado_inversion"),
            share=number("estado_aprobado_pct", 1),
        ),
        "portfolio_title": text["portfolio_title"].format(
            share=number("estado_sin_expediente_en_estudio_pct", 1)
        ),
        "incidence_title": text["incidence_title"],
        "implications": text["implications"],
        "method_title": text["method_title"],
    }
    copy["bullets"] = tuple(
        bullet.format(
            amount_round=number("headline_amount_round_mmusd"),
            aj24=number("aj_EIA_aprobado_24m", 1),
            center=number("eia_100m_aj_aprobado_24m_estimacion", 1),
            lo=number("eia_100m_aj_aprobado_24m_ic95_inf", 1),
            hi=number("eia_100m_aj_aprobado_24m_ic95_sup", 1),
            n_agg=number("estado_agregado_no_asignable_n"),
            amount_agg=number("estado_agregado_no_asignable_inversion"),
        )
        for bullet in text["bullets"]
    )
    copy["method_lines"] = tuple(
        line.format(
            population=number("sea_poblacion_admitida_n"),
            p_ini=str(int(values["poblacion_periodo_inicio"])),
            p_fin=str(int(values["poblacion_periodo_fin"])),
            fecha_datos=data_date,
            n_manual=number("cruces_revision_manual_n"),
            n_total=number("cartera_proyectos_n"),
            piso=number("headline_piso_pct", 1),
            techo=number("headline_techo_pct", 1),
        )
        for line in text["method_lines"]
    )
    return copy


def make_brief_portfolio_figure(
    metrics: pd.DataFrame, lang: str, path: Path
) -> Path:
    """Render the seven-category portfolio chart from verified register claims."""
    if lang not in TEXTS:
        raise ValueError(f"Unsupported language: {lang}")
    values = _metric_values(metrics)
    import matplotlib.pyplot as plt
    from matplotlib.ticker import FuncFormatter

    labels = {
        "es": (
            "Aprobado",
            "En evaluación",
            "Agregado Codelco\n(permisos múltiples o previos)",
            "Sin expediente: en estudio",
            "No determinado",
            "Desistido, rechazado o no calificado",
            "Pertinencia",
            "Inversión (MMUS$)",
        ),
        "en": (
            "Approved",
            "Under review",
            "Codelco aggregate\n(multiple or prior permits)",
            "No filing: in study",
            "Undetermined",
            "Withdrawn, rejected or not qualified",
            "Applicability ruling",
            "Investment (US$m)",
        ),
    }[lang]
    states = (
        (labels[0], "estado_aprobado_inversion", "#2F6F68"),
        (labels[1], "estado_en_evaluacion_inversion", "#4E8290"),
        (
            labels[2],
            "estado_agregado_no_asignable_inversion",
            "#7D8790",
        ),
        (labels[3], "estado_sin_expediente_en_estudio_inversion", "#C66B3D"),
        (labels[4], "estado_no_determinado_inversion", "#9CA3AA"),
        (
            labels[5],
            "estado_desistido_rechazado_o_no_calificado_inversion",
            "#B8BDC2",
        ),
        (labels[6], "estado_pertinencia_inversion", "#D3D6D8"),
    )
    ordered = sorted(
        (item for item in states if values[item[1]] > 0),
        key=lambda item: values[item[1]],
    )
    fig, ax = plt.subplots(figsize=(6.2, 4.2))
    bars = ax.barh(
        [item[0] for item in ordered],
        [values[item[1]] for item in ordered],
        color=[item[2] for item in ordered],
    )
    ax.bar_label(
        bars,
        labels=[format_number(values[item[1]], 0, lang) for item in ordered],
        padding=3,
        fontsize=8,
    )
    ax.set_xlabel(labels[7])
    ax.xaxis.set_major_formatter(
        FuncFormatter(lambda value, _position: format_number(value, 0, lang))
    )
    ax.grid(axis="x", color="#D9DEE2", linewidth=0.6)
    ax.set_axisbelow(True)
    ax.spines[["top", "right", "left"]].set_visible(False)
    ax.tick_params(axis="y", length=0, labelsize=8)
    ax.tick_params(axis="x", labelsize=8)
    fig.tight_layout(pad=0.6)
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(path, dpi=180, bbox_inches="tight", facecolor="white")
    plt.close(fig)
    return path


def make_brief_incidence_figure(lang: str, path: Path) -> Path:
    """Compare approval-only KM and Aalen-Johansen curves in one legible panel."""
    if lang not in TEXTS:
        raise ValueError(f"Unsupported language: {lang}")
    import matplotlib.pyplot as plt
    from matplotlib.lines import Line2D
    from matplotlib.ticker import PercentFormatter

    km = pd.read_parquet(KM_PATH)
    aj = pd.read_parquet(AJ_PATH)
    aj = aj.loc[aj["outcome"].eq("aprobado")]
    colors = {"DIA": "#176B87", "EIA": "#D97706"}
    fig, ax = plt.subplots(figsize=(6.2, 4.2))
    for instrument in ("DIA", "EIA"):
        km_group = km.loc[km["instrumento"].eq(instrument)].sort_values("time_days")
        aj_group = aj.loc[aj["instrumento"].eq(instrument)].sort_values("time_days")
        ax.step(
            km_group["time_days"] / DAYS_PER_MONTH,
            km_group["approval_probability"],
            where="post",
            color=colors[instrument],
            linewidth=2,
            linestyle=(0, (3, 2)),
        )
        ax.step(
            aj_group["time_days"] / DAYS_PER_MONTH,
            aj_group["cumulative_incidence"],
            where="post",
            color=colors[instrument],
            linewidth=2,
        )
    text = TEXTS[lang]
    instrument_handles = [
        Line2D([0], [0], color=colors[name], linewidth=2, label=name)
        for name in ("DIA", "EIA")
    ]
    method_handles = [
        Line2D(
            [0],
            [0],
            color="#3F4D53",
            linewidth=2,
            linestyle=(0, (3, 2)),
            label=text["km_legend"],
        ),
        Line2D(
            [0],
            [0],
            color="#3F4D53",
            linewidth=2,
            label=text["aj_legend"],
        ),
    ]
    first_legend = ax.legend(
        handles=instrument_handles, frameon=False, loc="upper left", fontsize=9
    )
    ax.add_artist(first_legend)
    ax.legend(handles=method_handles, frameon=False, loc="lower right", fontsize=9)
    ax.set_xlim(0, 72)
    ax.set_xticks(range(0, 73, 12))
    ax.set_ylim(0, 1)
    ax.yaxis.set_major_formatter(PercentFormatter(1, decimals=0))
    ax.set_xlabel(str(text["months_axis"]), fontsize=10)
    ax.set_ylabel(str(text["approval_axis"]), fontsize=10)
    ax.tick_params(labelsize=9)
    ax.grid(color="#D9DEE2", linewidth=0.6)
    ax.set_axisbelow(True)
    ax.spines[["top", "right"]].set_visible(False)
    fig.tight_layout(pad=0.7)
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(path, dpi=180, bbox_inches="tight", facecolor="white")
    plt.close(fig)
    return path


def _draw_page(metrics: pd.DataFrame, lang: str):  # noqa: ANN202
    import matplotlib.image as mpimg
    import matplotlib.pyplot as plt
    from matplotlib.patches import Rectangle

    portfolio_path = make_brief_portfolio_figure(
        metrics, lang, PORTFOLIO_FIGURE_PATHS[lang]
    )
    incidence_path = make_brief_incidence_figure(lang, INCIDENCE_FIGURE_PATHS[lang])
    left_image = mpimg.imread(portfolio_path)
    right_image = mpimg.imread(incidence_path)
    copy = _brief_copy(metrics, lang)

    ink = "#26343A"
    muted = "#617078"
    accent = "#B65C32"
    pale = "#EEF1F2"
    fig = plt.figure(figsize=(8.27, 11.69), facecolor="white")
    fig.subplots_adjust(0, 0, 1, 1)
    fig.patches.append(
        Rectangle(
            (0.055, 0.946), 0.89, 0.008, color=accent, transform=fig.transFigure
        )
    )
    headline = textwrap.fill(str(copy["headline"]), width=54)
    fig.text(
        0.055,
        0.922,
        headline,
        fontsize=16.0,
        fontweight="bold",
        color=ink,
        va="top",
        linespacing=1.05,
    )
    fig.text(0.055, 0.853, str(copy["subtitle"]), fontsize=10.5, color=accent, va="top")

    kpis = (
        (copy["km_title"], copy["km_body"]),
        (copy["bootstrap_title"], copy["bootstrap_body"]),
        (copy["evaluation_title"], copy["evaluation_body"]),
        (copy["approved_title"], copy["approved_body"]),
    )
    for index, (title, body) in enumerate(kpis):
        x = 0.055 + index * 0.224
        fig.patches.append(
            Rectangle((x, 0.744), 0.207, 0.09, color=pale, transform=fig.transFigure)
        )
        fig.text(
            x + 0.01,
            0.821,
            textwrap.fill(str(title), width=25),
            fontsize=6.4,
            fontweight="bold",
            color=muted,
            va="top",
            linespacing=1.12,
        )
        fig.text(
            x + 0.01,
            0.783,
            str(body),
            fontsize=8.1,
            fontweight="bold",
            color=ink,
            va="top",
            linespacing=1.28,
        )

    fig.text(
        0.055,
        0.715,
        textwrap.fill(str(copy["portfolio_title"]), width=45),
        fontsize=8.7,
        fontweight="bold",
        color=ink,
        va="top",
    )
    fig.text(
        0.52,
        0.715,
        textwrap.fill(str(copy["incidence_title"]), width=45),
        fontsize=8.7,
        fontweight="bold",
        color=ink,
        va="top",
    )
    left_ax = fig.add_axes((0.05, 0.455, 0.43, 0.225))
    left_ax.imshow(left_image)
    left_ax.axis("off")
    right_ax = fig.add_axes((0.515, 0.455, 0.43, 0.225))
    right_ax.imshow(right_image)
    right_ax.axis("off")

    fig.text(0.075, 0.415, str(copy["implications"]), fontsize=10.5, fontweight="bold", color=ink)
    y = 0.387
    for bullet in copy["bullets"]:
        wrapped = textwrap.fill(str(bullet), width=108)
        fig.text(0.061, y, "•", fontsize=10, color=accent, va="top")
        fig.text(0.078, y, wrapped, fontsize=8.5, color=ink, va="top", linespacing=1.32)
        y -= 0.046

    fig.patches.append(
        Rectangle(
            (0.055, 0.105),
            0.89,
            0.145,
            color="#F5F6F6",
            transform=fig.transFigure,
        )
    )
    fig.text(0.068, 0.232, str(copy["method_title"]), fontsize=9, fontweight="bold", color=ink)
    y = 0.211
    for line in copy["method_lines"]:
        wrapped = textwrap.fill(str(line), width=135)
        line_count = wrapped.count("\n") + 1
        fig.text(
            0.068,
            y,
            wrapped,
            fontsize=7.1,
            color=muted,
            va="top",
            linespacing=1.15,
        )
        y -= 0.017 * line_count
    fig.text(0.055, 0.07, AUTHOR_LINE, fontsize=7.5, color=muted)
    fig.text(
        0.945,
        0.07,
        "github.com/munozmartinezja/chile-mining-investment-pipeline",
        fontsize=7,
        color=muted,
        ha="right",
    )
    return fig, copy


def _claim_support(copy: dict[str, object]) -> list[tuple[str, str, str, str]]:
    """Map each semantic brief line to claims or a cited non-numeric source."""
    blocks = [
        ("titular", "headline", "estado_sin_expediente_en_estudio_pct"),
        (
            "subtitulo",
            "subtitle",
            "estado_sin_expediente_en_estudio_inversion;estado_sin_expediente_en_estudio_n;"
            "sea_fecha_datos_dia;sea_fecha_datos_mes;sea_fecha_datos_anio",
        ),
        ("kpi_1", "km_title", ""),
        (
            "kpi_1",
            "km_body",
            "aj_EIA_aprobado_24m;aj_EIA_aprobado_36m;"
            "aj_EIA_mes_50pct;aj_threshold_pct",
        ),
        ("kpi_2", "bootstrap_title", ""),
        (
            "kpi_2",
            "bootstrap_body",
            "eia_100m_aj_aprobado_24m_estimacion;eia_100m_aj_aprobado_24m_ic95_inf;"
            "eia_100m_aj_aprobado_24m_ic95_sup;eia_100m_n;confidence_level_pct",
        ),
        ("kpi_3", "evaluation_title", ""),
        ("kpi_3", "evaluation_body", "estado_en_evaluacion_inversion;estado_en_evaluacion_n"),
        ("kpi_4", "approved_title", ""),
        ("kpi_4", "approved_body", "estado_aprobado_inversion;estado_aprobado_pct"),
        ("figura_cartera", "portfolio_title", "estado_sin_expediente_en_estudio_pct"),
        ("figura_incidencia", "incidence_title", ""),
        ("seccion", "implications", ""),
        ("seccion", "method_title", ""),
    ]
    entries = [
        (
            block,
            str(copy[key]).replace("\n", " "),
            claim_ids,
            "" if claim_ids else "src/cmip/brief.py:TEXTS",
        )
        for block, key, claim_ids in blocks
    ]
    bullet_claims = (
        "headline_amount_round_mmusd;aj_EIA_aprobado_24m",
        "eia_100m_aj_aprobado_24m_estimacion;eia_100m_aj_aprobado_24m_ic95_inf;"
        "eia_100m_aj_aprobado_24m_ic95_sup;confidence_level_pct",
        "estado_agregado_no_asignable_n;estado_agregado_no_asignable_inversion",
    )
    entries.extend(
        ("bullet", str(text), claim_ids, "")
        for text, claim_ids in zip(copy["bullets"], bullet_claims, strict=True)
    )
    method_claims = (
        "sea_fecha_datos_dia;sea_fecha_datos_mes;sea_fecha_datos_anio",
        "sea_poblacion_admitida_n;poblacion_periodo_inicio;poblacion_periodo_fin",
        "",
        "cruces_revision_manual_n;cartera_proyectos_n;headline_piso_pct;headline_techo_pct",
        "",
    )
    method_evidence = (
        "data/SOURCES.md",
        "docs/survival_definitions.md",
        "docs/survival_definitions.md",
        "docs/validation_checklist.csv",
        "src/cmip/validation.py:build_claims_register",
    )
    entries.extend(
        ("metodo", str(text), claim_ids, evidence)
        for text, claim_ids, evidence in zip(
            copy["method_lines"], method_claims, method_evidence, strict=True
        )
    )
    entries.extend(
        [
            ("autor", AUTHOR_LINE, "", "src/cmip/config.py:AUTHOR_LINE"),
            (
                "pie",
                "github.com/munozmartinezja/chile-mining-investment-pipeline",
                "",
                "README.md",
            ),
            ("marca", "BORRADOR / DRAFT", "", "src/cmip/brief.py:--draft"),
        ]
    )
    return entries


def write_claims_map(outputs: dict[str, Path], metrics: pd.DataFrame) -> Path:
    """Write one support row for every line extracted from each generated PDF."""
    from pypdf import PdfReader

    records: list[dict[str, str]] = []
    for lang, path in outputs.items():
        copy = _brief_copy(metrics, lang)
        support = _claim_support(copy)
        text = "\n".join(page.extract_text() or "" for page in PdfReader(path).pages)
        for raw_line in text.splitlines():
            line = raw_line.strip().lstrip("\x7f•").strip()
            if not line:
                continue
            candidates = [entry for entry in support if line in entry[1] or entry[1] in line]
            if not candidates:
                raise ValueError(f"Unmapped extracted PDF line ({lang}): {line!r}")
            block, _full_text, claim_ids, evidence = candidates[0]
            records.append(
                {
                    "lang": lang,
                    "bloque": block,
                    "texto_renderizado": line,
                    "claim_ids": claim_ids,
                    "evidencia": evidence,
                }
            )
    result = pd.DataFrame(
        records, columns=["lang", "bloque", "texto_renderizado", "claim_ids", "evidencia"]
    )
    CLAIMS_MAP_PATH.parent.mkdir(parents=True, exist_ok=True)
    result.to_csv(CLAIMS_MAP_PATH, index=False)
    return CLAIMS_MAP_PATH


def _render_reportlab(
    metrics: pd.DataFrame, lang: str, path: Path, *, draft: bool = False
) -> None:
    """Draw native PDF text blocks so reading order and copy/paste are preserved."""
    from reportlab.lib import colors
    from reportlab.lib.enums import TA_LEFT, TA_RIGHT
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.pdfgen import canvas
    from reportlab.platypus import Paragraph

    copy = _brief_copy(metrics, lang)
    portfolio_path = make_brief_portfolio_figure(
        metrics, lang, PORTFOLIO_FIGURE_PATHS[lang]
    )
    incidence_path = make_brief_incidence_figure(lang, INCIDENCE_FIGURE_PATHS[lang])
    document = canvas.Canvas(str(path), pagesize=A4, pageCompression=1)
    page_width, page_height = A4
    ink = colors.HexColor("#26343A")
    muted = colors.HexColor("#617078")
    accent = colors.HexColor("#B65C32")
    pale = colors.HexColor("#EEF1F2")
    document.setFillColor(colors.white)
    document.rect(0, 0, page_width, page_height, fill=1, stroke=0)
    if draft:
        document.saveState()
        document.setFillColor(colors.Color(0.55, 0.55, 0.55, alpha=0.16))
        document.setFont("Helvetica-Bold", 42)
        document.translate(page_width / 2, page_height / 2)
        document.rotate(35)
        document.drawCentredString(0, 0, "BORRADOR / DRAFT")
        document.restoreState()

    def style(
        name: str,
        size: float,
        leading: float,
        color=ink,  # noqa: ANN001
        bold: bool = False,
        alignment: int = TA_LEFT,
        **kwargs,  # noqa: ANN003
    ) -> ParagraphStyle:
        return ParagraphStyle(
            name,
            fontName="Helvetica-Bold" if bold else "Helvetica",
            fontSize=size,
            leading=leading,
            textColor=color,
            alignment=alignment,
            splitLongWords=False,
            **kwargs,
        )

    def paragraph(
        value: object,
        x: float,
        top: float,
        width: float,
        paragraph_style: ParagraphStyle,
        height: float = 100,
    ) -> float:
        markup = escape(str(value)).replace("\n", "<br/>")
        block = Paragraph(markup, paragraph_style)
        _, used_height = block.wrap(width, height)
        block.drawOn(document, x, top - used_height)
        return used_height

    left = 33
    content_width = page_width - 2 * left
    document.setFillColor(accent)
    document.rect(left, page_height - 39, content_width, 6, fill=1, stroke=0)
    paragraph(
        copy["headline"],
        left,
        page_height - 50,
        content_width,
        style("headline", 14, 16, bold=True),
    )
    paragraph(
        copy["subtitle"],
        left,
        page_height - 102,
        content_width,
        style("subtitle", 10.5, 12, accent),
    )

    kpis = (
        (copy["km_title"], copy["km_body"]),
        (copy["bootstrap_title"], copy["bootstrap_body"]),
        (copy["evaluation_title"], copy["evaluation_body"]),
        (copy["approved_title"], copy["approved_body"]),
    )
    box_width = 123
    box_gap = (content_width - 4 * box_width) / 3
    box_bottom = page_height - 206
    for index, (title, body) in enumerate(kpis):
        x = left + index * (box_width + box_gap)
        document.setFillColor(pale)
        document.rect(x, box_bottom, box_width, 66, fill=1, stroke=0)
        paragraph(
            title,
            x + 7,
            box_bottom + 58,
            box_width - 14,
            style(f"kpi-title-{index}", 6.5, 7.5, muted, bold=True),
            24,
        )
        paragraph(
            body,
            x + 7,
            box_bottom + 31,
            box_width - 14,
            style(f"kpi-body-{index}", 8.1, 10, bold=True),
            28,
        )

    figure_width = 250
    figure_height = 200
    right_x = page_width - left - figure_width
    paragraph(
        copy["portfolio_title"],
        left,
        page_height - 226,
        figure_width,
        style("portfolio-title", 8.7, 10, bold=True),
        30,
    )
    paragraph(
        copy["incidence_title"],
        right_x,
        page_height - 226,
        figure_width,
        style("incidence-title", 8.7, 10, bold=True),
        30,
    )
    figure_bottom = page_height - 450
    for image_path, x in ((portfolio_path, left), (incidence_path, right_x)):
        document.drawImage(
            str(image_path),
            x,
            figure_bottom,
            figure_width,
            figure_height,
            preserveAspectRatio=True,
            anchor="c",
            mask="auto",
        )
    paragraph(
        copy["implications"],
        left,
        figure_bottom - 28,
        content_width,
        style("implications", 10.5, 12, bold=True),
    )
    bullet_style = style(
        "bullet",
        8.4,
        10.3,
        leftIndent=13,
        firstLineIndent=-10,
        bulletIndent=0,
        spaceAfter=4,
    )
    bullet_top = figure_bottom - 49
    for bullet in copy["bullets"]:
        block = Paragraph(f"<bullet>&bull;</bullet>{escape(str(bullet))}", bullet_style)
        _, used_height = block.wrap(content_width - 7, 60)
        block.drawOn(document, left + 4, bullet_top - used_height)
        bullet_top -= used_height + 4

    method_bottom = 80
    method_height = 180
    document.setFillColor(colors.HexColor("#F5F6F6"))
    document.rect(left, method_bottom, content_width, method_height, fill=1, stroke=0)
    paragraph(
        copy["method_title"],
        left + 9,
        method_bottom + method_height - 10,
        content_width - 18,
        style("method-title", 9, 11, bold=True),
    )
    method_style = style("method", 7.1, 10, muted)
    method_top = method_bottom + method_height - 27
    for line in copy["method_lines"]:
        used_height = paragraph(line, left + 9, method_top, content_width - 18, method_style, 24)
        method_top -= used_height + 1

    paragraph(AUTHOR_LINE, left, 52, 250, style("author", 7.5, 9, muted), 12)
    paragraph(
        "github.com/munozmartinezja/chile-mining-investment-pipeline",
        page_width - left - 280,
        52,
        280,
        style("repository", 7, 9, muted, alignment=TA_RIGHT),
        12,
    )

    document.showPage()
    document.save()


def render_brief(
    metrics: pd.DataFrame,
    lang: str,
    path: Path,
    portfolio_names: list[str] | None = None,
    draft: bool = False,
) -> Path:
    """Render exactly one A4 page using the mandatory ReportLab dependency."""
    del portfolio_names  # Names are intentionally never part of the rendering data flow.
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    _render_reportlab(metrics, lang, path, draft=draft)
    return path


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--lang", choices=["es", "en", "all"], default="all")
    parser.add_argument("--output-dir", type=Path, default=BRIEF_DIR)
    parser.add_argument("--draft", action="store_true")
    args = parser.parse_args()
    checklist = pd.read_csv(
        PROJECT_ROOT / "docs" / "validation_checklist.csv", keep_default_na=False
    )
    pending = checklist["respuesta_J"].astype(str).str.strip().eq("")
    if pending.any() and not args.draft:
        raise SystemExit(
            f"GATE: {int(pending.sum())} checklist rows have no respuesta_J; "
            "use --draft for watermarked review PDFs"
        )
    metrics = compute_brief_metrics()
    languages = ("es", "en") if args.lang == "all" else (args.lang,)
    outputs: dict[str, Path] = {}
    for language in languages:
        output = args.output_dir / f"brief_c1_{language}.pdf"
        outputs[language] = render_brief(metrics, language, output, draft=args.draft)
    claims_map = write_claims_map(outputs, metrics)
    print(metrics[["claim_id", "valor", "unidad", "estado"]].to_string(index=False))
    for output in outputs.values():
        print(f"Wrote {output}")
    print(f"Wrote {claims_map}")


if __name__ == "__main__":
    main()
