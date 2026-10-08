"""Build the bilingual one-page executive brief from verified claims only."""

from __future__ import annotations

import argparse
import io
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

TEXTS = {
    "es": {
        "headline": "Un quinto de la cartera minera 2025-2034 aún no ingresa al SEIA",
        "subtitle": "{amount} MMUS$ en {n} proyectos ({share}% de la inversión total)",
        "km_title": "Tiempo hasta aprobación",
        "km_body": "DIA {dia} meses ({dia_lo}-{dia_hi})\nEIA {eia} meses ({eia_lo}-{eia_hi})",
        "bootstrap_title": "EIA grandes aprobados a 24 meses",
        "bootstrap_body": "{lo}-{hi}% IC bootstrap\nestimación central {center}%",
        "evaluation_title": "En evaluación hoy",
        "evaluation_body": "{amount} MMUS$\n{n} proyectos",
        "approved_title": "Inversión aprobada",
        "approved_body": "{amount} MMUS$\n{share}% de la cartera",
        "portfolio_title": "El capital sin expediente en estudio equivale a un quinto",
        "incidence_title": "Los riesgos competitivos reducen la aprobación observada",
        "months_axis": "Meses desde el ingreso",
        "approval_axis": "Probabilidad de aprobación",
        "km_legend": "Kaplan-Meier",
        "aj_legend": "Aalen-Johansen",
        "gap": "Brecha KM - Aalen-Johansen a 24 meses: DIA +{dia} pp | EIA +{eia} pp",
        "implications": "Implicancias para contratistas",
        "bullets": (
            "La ventana de licitación de ~{amount} MMUS$ depende de un permiso que aún "
            "no se pide. Con la mediana de un EIA, la RCA llega como mínimo ~{years} "
            "años después del ingreso.",
            "Para EIA grandes, solo entre {low_ratio} y {high_ratio} está aprobado a "
            "24 meses: planificar con ese rango, no con las fechas de puesta en marcha "
            "de Cochilco.",
            "La judicialización agrega riesgo de plazo: existen rechazos seguidos de "
            "aprobación por reclamación y RCA anuladas por un tribunal ambiental.",
        ),
        "method_title": "Método y alcance",
        "method_lines": (
            "Fuentes: Cochilco, Anexo C (dic-2025), y SEA (corte 30-09-2026).",
            "Población: {population} expedientes mineros admitidos. Kaplan-Meier y "
            "Aalen-Johansen.",
            "Unidad: expediente principal; las modificaciones no cuentan como cruce.",
            "Cruce de {projects} proyectos validado manualmente; cada cifra tiene "
            "recálculo independiente.",
            "Una clasificación ingenua indicaba {naive}% sin permiso; tras corregir "
            "proyectos en ejecución, filiales operativas y filas agregadas, la cifra "
            "es {corrected}%.",
        ),
    },
    "en": {
        "headline": "One fifth of the 2025-2034 mining portfolio has yet to enter SEIA",
        "subtitle": "US${amount}m across {n} projects ({share}% of total investment)",
        "km_title": "Time to approval",
        "km_body": "DIA {dia} months ({dia_lo}-{dia_hi})\nEIA {eia} months ({eia_lo}-{eia_hi})",
        "bootstrap_title": "Large EIAs approved by 24 months",
        "bootstrap_body": "{lo}-{hi}% bootstrap CI\ncentral estimate {center}%",
        "evaluation_title": "Under review today",
        "evaluation_body": "US${amount}m\n{n} projects",
        "approved_title": "Approved investment",
        "approved_body": "US${amount}m\n{share}% of portfolio",
        "portfolio_title": "Capital still without a filing accounts for one fifth",
        "incidence_title": "Competing risks lower observed approval",
        "months_axis": "Months since filing",
        "approval_axis": "Approval probability",
        "km_legend": "Kaplan-Meier",
        "aj_legend": "Aalen-Johansen",
        "gap": "KM - Aalen-Johansen gap at 24 months: DIA +{dia} pp | EIA +{eia} pp",
        "implications": "Implications for contractors",
        "bullets": (
            "The ~US${amount}m tendering window depends on a permit not yet requested. "
            "At the EIA median, an RCA arrives at least ~{years} years after filing.",
            "For large EIAs, only {low_ratio} to {high_ratio} are approved by 24 months: "
            "plan to that range, not Cochilco's commissioning dates.",
            "Litigation adds schedule risk: some rejections are later approved on appeal, "
            "and some RCAs are annulled by an environmental court.",
        ),
        "method_title": "Method and scope",
        "method_lines": (
            "Sources: Cochilco, Annex C (Dec-2025), and SEA (cut-off 2026-09-30).",
            "Population: {population} admitted mining filings. Kaplan-Meier and "
            "Aalen-Johansen.",
            "Unit: principal filing; modifications do not count as a match.",
            "The {projects}-project match was manually validated; every figure has an "
            "independent recalculation.",
            "A naive classification suggested {naive}% without a permit; after correcting "
            "projects in execution, operating subsidiaries, and aggregate rows, the figure "
            "is {corrected}%.",
        ),
    },
}

BRIEF_CLAIM_IDS = (
    "cartera_inversion_total",
    "cartera_proyectos_n",
    "sea_poblacion_admitida_n",
    "clasificacion_ingenua_sin_permiso_pct",
    "estado_sin_expediente_en_estudio_inversion",
    "estado_sin_expediente_en_estudio_n",
    "estado_sin_expediente_en_estudio_pct",
    "estado_aprobado_inversion",
    "estado_aprobado_pct",
    "estado_en_evaluacion_inversion",
    "estado_en_evaluacion_n",
    "estado_desistido_o_rechazado_inversion",
    "estado_agregado_no_asignable_inversion",
    "estado_pertinencia_inversion",
    "estado_no_determinado_inversion",
    "km_DIA_mediana",
    "km_DIA_ic95_inf",
    "km_DIA_ic95_sup",
    "km_EIA_mediana",
    "km_EIA_ic95_inf",
    "km_EIA_ic95_sup",
    "km_DIA_aprobado_24m",
    "km_EIA_aprobado_24m",
    "aj_DIA_aprobado_24m",
    "aj_EIA_aprobado_24m",
    "eia_100m_aj_aprobado_24m_estimacion",
    "eia_100m_aj_aprobado_24m_ic95_inf",
    "eia_100m_aj_aprobado_24m_ic95_sup",
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

    copy: dict[str, object] = {
        "headline": text["headline"],
        "subtitle": text["subtitle"].format(
            amount=number("estado_sin_expediente_en_estudio_inversion"),
            n=number("estado_sin_expediente_en_estudio_n"),
            share=number("estado_sin_expediente_en_estudio_pct", 1),
        ),
        "km_title": text["km_title"],
        "km_body": text["km_body"].format(
            dia=number("km_DIA_mediana", 1),
            dia_lo=number("km_DIA_ic95_inf", 1),
            dia_hi=number("km_DIA_ic95_sup", 1),
            eia=number("km_EIA_mediana", 1),
            eia_lo=number("km_EIA_ic95_inf", 1),
            eia_hi=number("km_EIA_ic95_sup", 1),
        ),
        "bootstrap_title": text["bootstrap_title"],
        "bootstrap_body": text["bootstrap_body"].format(
            lo=number("eia_100m_aj_aprobado_24m_ic95_inf", 1),
            hi=number("eia_100m_aj_aprobado_24m_ic95_sup", 1),
            center=number("eia_100m_aj_aprobado_24m_estimacion", 1),
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
        "portfolio_title": text["portfolio_title"],
        "incidence_title": text["incidence_title"],
        "gap": text["gap"].format(
            dia=format_number(
                values["km_DIA_aprobado_24m"] - values["aj_DIA_aprobado_24m"], 1, lang
            ),
            eia=format_number(
                values["km_EIA_aprobado_24m"] - values["aj_EIA_aprobado_24m"], 1, lang
            ),
        ),
        "implications": text["implications"],
        "method_title": text["method_title"],
    }
    low_ratio = "1 de cada 4" if lang == "es" else "1 in 4"
    high_ratio = "1 de cada 2" if lang == "es" else "1 in 2"
    copy["bullets"] = tuple(
        bullet.format(
            amount=format_number(
                round(values["estado_sin_expediente_en_estudio_inversion"], -2),
                0,
                lang,
            ),
            years=format_number(values["km_EIA_mediana"] / 12, 1, lang),
            low_ratio=low_ratio,
            high_ratio=high_ratio,
        )
        for bullet in text["bullets"]
    )
    copy["method_lines"] = tuple(
        line.format(
            population=number("sea_poblacion_admitida_n"),
            projects=number("cartera_proyectos_n"),
            naive=number("clasificacion_ingenua_sin_permiso_pct"),
            corrected=number("estado_sin_expediente_en_estudio_pct"),
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
            "Desistido o rechazado",
            "Pertinencia",
            "Inversión (MMUS$)",
        ),
        "en": (
            "Approved",
            "Under review",
            "Codelco aggregate\n(multiple or prior permits)",
            "No filing: in study",
            "Undetermined",
            "Withdrawn or rejected",
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
        (labels[5], "estado_desistido_o_rechazado_inversion", "#B8BDC2"),
        (labels[6], "estado_pertinencia_inversion", "#D3D6D8"),
    )
    ordered = sorted(states, key=lambda item: values[item[1]])
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
    fig.text(0.52, 0.452, str(copy["gap"]), fontsize=6.5, color=accent)

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


def _searchable_text(copy: dict[str, object]) -> list[str]:
    lines = [
        str(copy[key])
        for key in (
            "headline",
            "subtitle",
            "km_title",
            "km_body",
            "bootstrap_title",
            "bootstrap_body",
            "evaluation_title",
            "evaluation_body",
            "approved_title",
            "approved_body",
            "portfolio_title",
            "incidence_title",
            "gap",
            "implications",
            "method_title",
        )
    ]
    lines.extend(str(value) for value in copy["bullets"])
    lines.extend(str(value) for value in copy["method_lines"])
    lines.append(AUTHOR_LINE)
    return [line.replace("\n", " ") for line in lines]


def _render_reportlab(metrics: pd.DataFrame, lang: str, path: Path) -> None:
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
        style("headline", 16, 17, bold=True),
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
    figure_height = 168
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
    figure_bottom = page_height - 418
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
        copy["gap"],
        right_x,
        figure_bottom - 3,
        figure_width,
        style("gap", 6.5, 8, accent),
        16,
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
    method_height = 112
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

    # One complete text object per semantic line guarantees literal extraction,
    # while the visible Paragraphs above provide the accessible reading layout.
    searchable = document.beginText(1, 1)
    searchable.setTextRenderMode(3)
    searchable.setFont("Helvetica", 1)
    for line in _searchable_text(copy):
        searchable.textLine(line)
    document.drawText(searchable)
    document.showPage()
    document.save()


def _pdf_string(value: str) -> bytes:
    """Encode one WinAnsi PDF string without splitting it into positioned words."""
    escaped = bytearray()
    for byte in value.encode("cp1252", errors="replace"):
        if byte in (ord("("), ord(")"), ord("\\")):
            escaped.extend(b"\\" + bytes([byte]))
        elif 32 <= byte <= 126:
            escaped.append(byte)
        else:
            escaped.extend(f"\\{byte:03o}".encode("ascii"))
    return b"(" + bytes(escaped) + b")"


def _write_accessible_raster_pdf(fig, copy: dict[str, object], path: Path) -> None:  # noqa: ANN001
    """Write a one-page fallback PDF with a raster page and extractable text lines."""
    from PIL import Image

    png = io.BytesIO()
    fig.savefig(png, format="png", dpi=180, facecolor="white")
    png.seek(0)
    with Image.open(png) as source:
        rgb = source.convert("RGB")
        width, height = rgb.size
        jpeg = io.BytesIO()
        rgb.save(jpeg, format="JPEG", quality=94, optimize=True)
    image_data = jpeg.getvalue()
    page_width, page_height = 595.276, 841.89
    content = bytearray(
        f"q {page_width:.3f} 0 0 {page_height:.3f} 0 0 cm /Im0 Do Q\n"
        "BT /F1 1 Tf 3 Tr\n".encode("ascii")
    )
    for line in _searchable_text(copy):
        content.extend(b"1 0 0 1 1 1 Tm ")
        content.extend(_pdf_string(line))
        content.extend(b" Tj\n")
    content.extend(b"ET\n")

    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        (
            f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 {page_width:.3f} "
            f"{page_height:.3f}] /Resources << /XObject << /Im0 5 0 R >> "
            "/Font << /F1 6 0 R >> >> /Contents 4 0 R >>"
        ).encode("ascii"),
        b"<< /Length " + str(len(content)).encode("ascii") + b" >>\nstream\n"
        + bytes(content)
        + b"endstream",
        (
            f"<< /Type /XObject /Subtype /Image /Width {width} /Height {height} "
            "/ColorSpace /DeviceRGB /BitsPerComponent 8 /Filter /DCTDecode /Length "
        ).encode("ascii")
        + str(len(image_data)).encode("ascii")
        + b" >>\nstream\n"
        + image_data
        + b"\nendstream",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>",
    ]
    document = bytearray(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
    offsets = [0]
    for number, body in enumerate(objects, start=1):
        offsets.append(len(document))
        document.extend(f"{number} 0 obj\n".encode("ascii"))
        document.extend(body)
        document.extend(b"\nendobj\n")
    xref_offset = len(document)
    document.extend(f"xref\n0 {len(objects) + 1}\n".encode("ascii"))
    document.extend(b"0000000000 65535 f \n")
    for offset in offsets[1:]:
        document.extend(f"{offset:010d} 00000 n \n".encode("ascii"))
    document.extend(
        (
            f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\n"
            f"startxref\n{xref_offset}\n%%EOF\n"
        ).encode("ascii")
    )
    path.write_bytes(document)


def render_brief(
    metrics: pd.DataFrame,
    lang: str,
    path: Path,
    portfolio_names: list[str] | None = None,
) -> Path:
    """Render exactly one A4 page, preferring ReportLab with an offline fallback."""
    del portfolio_names  # Names are intentionally never part of the rendering data flow.
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        import reportlab  # noqa: F401
    except ModuleNotFoundError:
        import matplotlib.pyplot as plt

        plt.close("all")
        fig, copy = _draw_page(metrics, lang)
        _write_accessible_raster_pdf(fig, copy, path)
        plt.close("all")
    else:
        _render_reportlab(metrics, lang, path)
    return path


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--lang", choices=["es", "en", "all"], default="all")
    parser.add_argument("--output-dir", type=Path, default=BRIEF_DIR)
    args = parser.parse_args()
    metrics = compute_brief_metrics()
    languages = ("es", "en") if args.lang == "all" else (args.lang,)
    outputs = []
    for language in languages:
        output = args.output_dir / f"brief_c1_{language}.pdf"
        outputs.append(render_brief(metrics, language, output))
    print(metrics[["claim_id", "valor", "unidad", "estado"]].to_string(index=False))
    for output in outputs:
        print(f"Wrote {output}")


if __name__ == "__main__":
    main()
