"""Time-to-approval and competing-risk analysis for SEA mining projects."""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Callable
from pathlib import Path
from statistics import NormalDist

import numpy as np
import pandas as pd

from cmip.config import (
    PROCESSED_DIR,
    PROJECT_ROOT,
    SEA_DATA_CURRENCY_DATE,
    SEA_DOWNLOAD_DATE,
)

COMPETING_EVENT_CODES = {
    "aprobado": 1,
    "desistido_o_abandonado": 2,
    "rechazado": 3,
    "termino_anticipado": 4,
}
EVENT_LABELS = {
    "aprobado": "Aprobado",
    "desistido_o_abandonado": "Desistido o abandonado",
    "rechazado": "Rechazado",
    "termino_anticipado": "Término anticipado",
}
HORIZON_MONTHS = (6, 12, 24, 36)
DAYS_PER_MONTH = 365.25 / 12
# lifelines' Aalen-Johansen estimator resets the CIF to 0 at t=0, silently dropping
# events observed on the submission day. Such events are shifted to half a day for
# estimation only; stored durations keep their original value of 0.
ZERO_DURATION_OFFSET_DAYS = 0.5
SEA_PATH = PROJECT_ROOT / "data" / "interim" / "sea_mining.parquet"
POPULATION_PATH = PROCESSED_DIR / "survival_population.parquet"
KM_PATH = PROCESSED_DIR / "survival_km.parquet"
KM_SUMMARY_PATH = PROCESSED_DIR / "survival_km_summary.parquet"
AJ_PATH = PROCESSED_DIR / "survival_competing_risks.parquet"
AJ_SUMMARY_PATH = PROCESSED_DIR / "survival_competing_risks_summary.parquet"
TREND_PATH = PROCESSED_DIR / "survival_trend.parquet"
COX_PATH = PROCESSED_DIR / "survival_cox.parquet"
RESULTS_PATH = PROJECT_ROOT / "docs" / "survival_results.md"
POPULATION_EXCLUSIONS_PATH = PROJECT_ROOT / "docs" / "population_exclusions.csv"
POPULATION_EXCLUSIONS_REVIEW_PATH = (
    PROJECT_ROOT / "docs" / "population_exclusions_review.csv"
)
EXCLUDED_MAIN_POPULATION_TIPOLOGIAS = frozenset({"i5", "i5.1", "i5.2"})
EXCLUDED_MAIN_POPULATION_NAME_PATTERNS = (
    ("árido", re.compile(r"aridos?")),
    ("pozo lastrero", re.compile(r"pozo\s+lastrero")),
    ("empréstito", re.compile(r"emprestitos?")),
    (
        "extracción de material",
        re.compile(r"extraccion\s+de\s+material(?:es)?"),
    ),
)


def _normalized_expediente_name(value: object) -> str:
    normalized = unicodedata.normalize("NFKD", str(value).casefold())
    return " ".join(
        "".join(
            character
            for character in normalized
            if not unicodedata.combining(character)
        ).split()
    )


def main_population_exclusion_reasons(sea_mining: pd.DataFrame) -> pd.Series:
    """Return an auditable reason for every record excluded by the main rule."""
    names = sea_mining.get(
        "exp_nombre", pd.Series("", index=sea_mining.index, dtype="string")
    ).fillna("")
    reasons: list[str] = []
    for tipologia, name in zip(
        sea_mining["tipologia"].fillna("").astype(str), names, strict=True
    ):
        matches = []
        if tipologia.casefold().startswith("i5"):
            matches.append("tipología i5*")
        normalized_name = _normalized_expediente_name(name)
        if tipologia.casefold() not in {"i3", "i4"}:
            matches.extend(
                f"nombre: {label}"
                for label, pattern in EXCLUDED_MAIN_POPULATION_NAME_PATTERNS
                if pattern.search(normalized_name)
            )
        reasons.append("; ".join(matches))
    return pd.Series(reasons, index=sea_mining.index, dtype="string")


def main_population_review_reasons(sea_mining: pd.DataFrame) -> pd.Series:
    """Return name-rule matches held for review because their type is i3 or i4."""
    names = sea_mining.get(
        "exp_nombre", pd.Series("", index=sea_mining.index, dtype="string")
    ).fillna("")
    reasons: list[str] = []
    for tipologia, name in zip(
        sea_mining["tipologia"].fillna("").astype(str), names, strict=True
    ):
        matches: list[str] = []
        if tipologia.casefold() in {"i3", "i4"}:
            normalized_name = _normalized_expediente_name(name)
            matches.extend(
                f"nombre: {label}"
                for label, pattern in EXCLUDED_MAIN_POPULATION_NAME_PATTERNS
                if pattern.search(normalized_name)
            )
        reasons.append(
            f"revisión i3/i4: {'; '.join(matches)}" if matches else ""
        )
    return pd.Series(reasons, index=sea_mining.index, dtype="string")


def build_population_exclusions(sea_mining: pd.DataFrame) -> pd.DataFrame:
    """Return otherwise eligible records removed from the main population."""
    reasons = main_population_exclusion_reasons(sea_mining)
    eligible = sea_mining["admitido"].eq(True) & sea_mining[
        "fecha_inconsistente"
    ].eq(False)
    columns = ["exp_id", "exp_nombre", "tipologia", "instrumento"]
    exclusions = sea_mining.loc[eligible & reasons.ne(""), columns].copy()
    exclusions["motivo"] = reasons.loc[exclusions.index]
    return exclusions.sort_values(["instrumento", "exp_id"]).reset_index(drop=True)


def build_population_exclusions_review(sea_mining: pd.DataFrame) -> pd.DataFrame:
    """Return i3/i4 name matches that require J's review instead of exclusion."""
    reasons = main_population_review_reasons(sea_mining)
    eligible = sea_mining["admitido"].eq(True) & sea_mining[
        "fecha_inconsistente"
    ].eq(False)
    columns = ["exp_id", "exp_nombre", "tipologia", "instrumento"]
    review = sea_mining.loc[eligible & reasons.ne(""), columns].copy()
    review["motivo"] = reasons.loc[review.index]
    return review.sort_values(["instrumento", "exp_id"]).reset_index(drop=True)


def build_survival_population(sea_mining: pd.DataFrame) -> pd.DataFrame:
    """Return admitted, date-consistent records with estimator event encodings."""
    excluded = main_population_exclusion_reasons(sea_mining).ne("")
    population = sea_mining.loc[
        sea_mining["admitido"].eq(True)
        & sea_mining["fecha_inconsistente"].eq(False)
        & ~excluded
    ].copy()
    if population["duracion_dias"].isna().any():
        raise ValueError("Filtered survival population contains missing durations")
    if population["instrumento"].isna().any():
        raise ValueError("Filtered survival population contains missing instruments")
    population = population.rename(columns={"duracion_dias": "duration_days"})
    population["duration_days"] = population["duration_days"].astype(float)
    population["approval_event"] = population["evento"].eq("aprobado").astype(int)
    population["competing_event"] = (
        population["evento"].map(COMPETING_EVENT_CODES).fillna(0).astype(int)
    )
    return population.reset_index(drop=True)


def _km_factory():
    try:
        from lifelines import KaplanMeierFitter
    except ModuleNotFoundError:  # pragma: no cover - exercised only in offline builds
        return _FallbackKaplanMeierFitter()
    return KaplanMeierFitter()


def _aj_factory():
    try:
        from lifelines import AalenJohansenFitter
    except ModuleNotFoundError:  # pragma: no cover - exercised only in offline builds
        return _FallbackAalenJohansenFitter()
    return AalenJohansenFitter(seed=20261001)


class _FallbackKaplanMeierFitter:
    """Small offline KM implementation matching the lifelines result contract."""

    def fit(self, durations, event_observed, label):  # noqa: ANN001
        duration = pd.Series(durations, dtype=float).reset_index(drop=True)
        observed = pd.Series(event_observed, dtype=int).reset_index(drop=True)
        survival = 1.0
        greenwood = 0.0
        z_value = NormalDist().inv_cdf(0.975)
        timeline = sorted(duration.unique())
        records = [] if timeline and timeline[0] == 0 else [(0.0, 1.0, 1.0, 1.0)]
        for time in timeline:
            at_risk = int(duration.ge(time).sum())
            events = int((duration.eq(time) & observed.eq(1)).sum())
            if events:
                survival *= 1 - events / at_risk
                if at_risk > events:
                    greenwood += events / (at_risk * (at_risk - events))
            if survival in {0.0, 1.0}:
                lower = upper = survival
            else:
                log_log = np.log(-np.log(survival))
                standard_error = np.sqrt(greenwood) / abs(np.log(survival))
                lower = np.exp(-np.exp(log_log + z_value * standard_error))
                upper = np.exp(-np.exp(log_log - z_value * standard_error))
            records.append((float(time), survival, lower, upper))
        frame = pd.DataFrame(
            records,
            columns=["timeline", label, f"{label}_lower_0.95", f"{label}_upper_0.95"],
        ).set_index("timeline")
        self.survival_function_ = frame[[label]]
        self.confidence_interval_ = frame[
            [f"{label}_lower_0.95", f"{label}_upper_0.95"]
        ]
        return self


class _FallbackAalenJohansenFitter:
    """Small offline Aalen–Johansen implementation for cumulative incidence."""

    def fit(  # noqa: ANN001
        self,
        durations,
        event_observed,
        event_of_interest,
        label,
    ):
        duration = pd.Series(durations, dtype=float).reset_index(drop=True)
        observed = pd.Series(event_observed, dtype=int).reset_index(drop=True)
        overall_survival = 1.0
        cumulative_incidence = 0.0
        timeline = sorted(duration.unique())
        records = [] if timeline and timeline[0] == 0 else [(0.0, 0.0)]
        for time in timeline:
            at_risk = int(duration.ge(time).sum())
            target_events = int(
                (duration.eq(time) & observed.eq(event_of_interest)).sum()
            )
            all_events = int((duration.eq(time) & observed.ne(0)).sum())
            cumulative_incidence += overall_survival * target_events / at_risk
            overall_survival *= 1 - all_events / at_risk
            records.append((float(time), cumulative_incidence))
        self.cumulative_density_ = pd.DataFrame(
            records, columns=["event_at", label]
        ).set_index("event_at")
        self.confidence_interval_ = None
        return self


def _estimation_durations(durations: pd.Series) -> pd.Series:
    """Return durations safe for lifelines: zero-day events moved to half a day."""
    return durations.where(durations > 0, ZERO_DURATION_OFFSET_DAYS)


def fit_kaplan_meier(
    population: pd.DataFrame, fitter_factory: Callable[[], object] = _km_factory
) -> dict[str, object]:
    """Fit one approval KM curve per instrument over the supplied population."""
    fits: dict[str, object] = {}
    for instrument, group in population.groupby("instrumento", sort=True):
        fitter = fitter_factory()
        fits[str(instrument)] = fitter.fit(
            _estimation_durations(group["duration_days"]),
            group["approval_event"],
            label=str(instrument),
        )
    return fits


def fit_competing_risks(
    population: pd.DataFrame, fitter_factory: Callable[[], object] = _aj_factory
) -> dict[tuple[str, str], object]:
    """Fit an Aalen–Johansen cumulative incidence for each instrument/outcome."""
    fits: dict[tuple[str, str], object] = {}
    for instrument, group in population.groupby("instrumento", sort=True):
        for outcome, code in COMPETING_EVENT_CODES.items():
            fitter = fitter_factory()
            label = f"{instrument}: {outcome}"
            fits[(str(instrument), outcome)] = fitter.fit(
                _estimation_durations(group["duration_days"]),
                group["competing_event"],
                event_of_interest=code,
                label=label,
            )
    return fits


def _curve_frame(frame: pd.DataFrame, value_name: str) -> pd.DataFrame:
    result = frame.iloc[:, [0]].reset_index()
    result.columns = ["time_days", value_name]
    return result


def _confidence_frame(frame: pd.DataFrame, lower_name: str, upper_name: str) -> pd.DataFrame:
    lower_columns = [column for column in frame.columns if "lower" in str(column)]
    upper_columns = [column for column in frame.columns if "upper" in str(column)]
    if lower_columns and upper_columns:
        result = frame[[lower_columns[0], upper_columns[0]]].reset_index()
    else:
        result = frame.iloc[:, :2].reset_index()
    result.columns = ["time_days", lower_name, upper_name]
    return result


def _step_value(frame: pd.DataFrame, column: str, time_days: float, default: float) -> float:
    eligible = frame.loc[frame["time_days"] <= time_days, column]
    return float(eligible.iloc[-1]) if not eligible.empty else default


def _crossing_time(frame: pd.DataFrame, column: str, threshold: float = 0.5) -> float:
    crossed = frame.loc[frame[column] <= threshold, "time_days"]
    return float(crossed.iloc[0]) if not crossed.empty else float("inf")


def extract_km_tables(
    fits: dict[str, object],
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Convert fitted KM objects into tidy curve and horizon-summary tables."""
    curves: list[pd.DataFrame] = []
    summaries: list[dict[str, float | str]] = []
    for instrument, fitter in fits.items():
        survival = _curve_frame(fitter.survival_function_, "survival_probability")
        confidence = _confidence_frame(
            fitter.confidence_interval_, "survival_ci_lower", "survival_ci_upper"
        )
        curve = survival.merge(confidence, on="time_days", how="left")
        curve.insert(0, "instrumento", instrument)
        curve["approval_probability"] = 1 - curve["survival_probability"]
        curve["approval_ci_lower"] = 1 - curve["survival_ci_upper"]
        curve["approval_ci_upper"] = 1 - curve["survival_ci_lower"]
        curves.append(curve)

        summary: dict[str, float | str] = {
            "instrumento": instrument,
            "mediana_km_meses": _crossing_time(curve, "survival_probability") / DAYS_PER_MONTH,
            "mediana_ic95_inf_meses": _crossing_time(curve, "survival_ci_lower") / DAYS_PER_MONTH,
            "mediana_ic95_sup_meses": _crossing_time(curve, "survival_ci_upper") / DAYS_PER_MONTH,
        }
        for months in HORIZON_MONTHS:
            horizon = months * DAYS_PER_MONTH
            summary[f"prob_aprobacion_{months}m"] = 1 - _step_value(
                curve, "survival_probability", horizon, 1.0
            )
            summary[f"prob_aprobacion_{months}m_ic95_inf"] = 1 - _step_value(
                curve, "survival_ci_upper", horizon, 1.0
            )
            summary[f"prob_aprobacion_{months}m_ic95_sup"] = 1 - _step_value(
                curve, "survival_ci_lower", horizon, 1.0
            )
        summaries.append(summary)
    return pd.concat(curves, ignore_index=True), pd.DataFrame(summaries)


def extract_competing_risk_tables(
    fits: dict[tuple[str, str], object],
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Convert fitted Aalen–Johansen objects into tidy curve and horizon tables."""
    curves: list[pd.DataFrame] = []
    summaries: list[dict[str, float | str | int]] = []
    for (instrument, outcome), fitter in fits.items():
        curve = _curve_frame(fitter.cumulative_density_, "cumulative_incidence")
        curve.insert(0, "outcome", outcome)
        curve.insert(0, "instrumento", instrument)
        confidence = getattr(fitter, "confidence_interval_", None)
        if confidence is not None and confidence.shape[1] >= 2:
            ci = _confidence_frame(confidence, "ci_lower", "ci_upper")
            curve = curve.merge(ci, on="time_days", how="left")
        else:
            curve["ci_lower"] = np.nan
            curve["ci_upper"] = np.nan
        curves.append(curve)
        for months in HORIZON_MONTHS:
            summaries.append(
                {
                    "instrumento": instrument,
                    "outcome": outcome,
                    "horizonte_meses": months,
                    "incidencia_acumulada": _step_value(
                        curve,
                        "cumulative_incidence",
                        months * DAYS_PER_MONTH,
                        0.0,
                    ),
                    "ci_lower": _step_value(curve, "ci_lower", months * DAYS_PER_MONTH, np.nan),
                    "ci_upper": _step_value(curve, "ci_upper", months * DAYS_PER_MONTH, np.nan),
                }
            )
    return pd.concat(curves, ignore_index=True), pd.DataFrame(summaries)


def build_trend_table(population: pd.DataFrame) -> pd.DataFrame:
    """Median observed duration among approvals by entry cohort and instrument."""
    approved = population.loc[population["evento"].eq("aprobado")].copy()
    approved["anio_ingreso"] = approved["fecha_ingreso"].dt.year
    grouped = (
        approved.groupby(["instrumento", "anio_ingreso"], observed=True)["duration_days"]
        .agg(mediana_dias_aprobados="median", n_aprobados="size")
        .reset_index()
    )
    instruments = sorted(population["instrumento"].dropna().astype(str).unique())
    complete_index = pd.MultiIndex.from_product(
        [instruments, range(2011, 2027)], names=["instrumento", "anio_ingreso"]
    )
    result = (
        grouped.set_index(["instrumento", "anio_ingreso"]).reindex(complete_index).reset_index()
    )
    result["n_aprobados"] = result["n_aprobados"].fillna(0).astype(int)
    result["cohorte_incompleta"] = result["anio_ingreso"].ge(2025)
    return result


def _macro_zone(region: object) -> str:
    normalized = str(region).strip().casefold()
    if normalized in {"xv", "i", "ii", "arica y parinacota", "tarapacá", "tarapaca", "antofagasta"}:
        return "Norte Grande"
    if normalized in {"iii", "iv", "atacama", "coquimbo"}:
        return "Norte Chico"
    return "Centro-Sur"


def fit_cox_model(population: pd.DataFrame) -> tuple[pd.DataFrame, dict[str, object]]:
    """Fit an exploratory cause-specific Cox model and test proportional hazards."""
    try:
        from lifelines import CoxPHFitter
        from lifelines.statistics import proportional_hazard_test
    except ModuleNotFoundError as error:  # pragma: no cover - environment dependent
        raise RuntimeError("lifelines is required; run `make setup`") from error

    frame = population.loc[population["inversion_musd"].gt(0)].copy()
    frame["log_inversion"] = np.log(frame["inversion_musd"])
    frame["anio_ingreso"] = frame["fecha_ingreso"].dt.year.astype(float)
    frame["anio_ingreso"] -= frame["anio_ingreso"].median()
    frame["macro_zona"] = frame["region"].map(_macro_zone)
    model = frame[
        [
            "duration_days",
            "approval_event",
            "instrumento",
            "log_inversion",
            "macro_zona",
            "anio_ingreso",
        ]
    ].dropna()
    encoded = pd.get_dummies(
        model,
        columns=["instrumento", "macro_zona"],
        drop_first=True,
        dtype=float,
    )
    cph = CoxPHFitter()
    cph.fit(encoded, duration_col="duration_days", event_col="approval_event")
    ph = proportional_hazard_test(cph, encoded, time_transform="rank")
    ph_pvalues = ph.summary["p"].to_dict()
    violated = any(float(value) < 0.05 for value in ph_pvalues.values())
    stratified = False
    stratified_ph_pvalues: dict[str, float] | None = None
    if violated:
        stratified_model = pd.get_dummies(
            model,
            columns=["macro_zona"],
            drop_first=True,
            dtype=float,
        )
        cph = CoxPHFitter()
        cph.fit(
            stratified_model,
            duration_col="duration_days",
            event_col="approval_event",
            strata=["instrumento"],
        )
        stratified_ph = proportional_hazard_test(
            cph, stratified_model, time_transform="rank"
        )
        stratified_ph_pvalues = stratified_ph.summary["p"].to_dict()
        stratified = True

    summary = cph.summary.reset_index().rename(columns={"covariate": "variable"})
    if "variable" not in summary.columns:
        summary = summary.rename(columns={summary.columns[0]: "variable"})
    result = summary[
        ["variable", "exp(coef)", "exp(coef) lower 95%", "exp(coef) upper 95%", "p"]
    ].rename(
        columns={
            "exp(coef)": "hazard_ratio",
            "exp(coef) lower 95%": "ic95_inf",
            "exp(coef) upper 95%": "ic95_sup",
            "p": "p_value",
        }
    )
    metadata: dict[str, object] = {
        "n": len(model),
        "eventos": int(model["approval_event"].sum()),
        "ph_pvalues": ph_pvalues,
        "ph_violated": violated,
        "stratified_by_instrument": stratified,
        "stratified_ph_pvalues": stratified_ph_pvalues,
        "ph_violated_after_stratification": bool(
            stratified_ph_pvalues
            and any(float(value) < 0.05 for value in stratified_ph_pvalues.values())
        ),
    }
    return result, metadata


def _format_number(value: object, decimals: int = 1) -> str:
    if value is None or pd.isna(value):
        return "—"
    if np.isinf(float(value)):
        return "No alcanzada"
    return f"{float(value):.{decimals}f}"


def _markdown_table(headers: list[str], rows: list[list[str]]) -> str:
    lines = ["| " + " | ".join(headers) + " |", "| " + " | ".join(["---"] * len(headers)) + " |"]
    lines.extend("| " + " | ".join(row) + " |" for row in rows)
    return "\n".join(lines)


def write_results_markdown(
    km_summary: pd.DataFrame,
    aj_summary: pd.DataFrame,
    trend: pd.DataFrame,
    cox: pd.DataFrame | None,
    cox_metadata: dict[str, object] | None,
    cox_error: str | None = None,
    output_path: Path = RESULTS_PATH,
) -> None:
    """Write publication-ready tables and explicit statistical assumptions."""
    km_rows = []
    for row in km_summary.to_dict("records"):
        km_rows.append(
            [
                str(row["instrumento"]),
                _format_number(row["mediana_km_meses"]),
                f"{_format_number(row['mediana_ic95_inf_meses'])}–{_format_number(row['mediana_ic95_sup_meses'])}",
                *[_format_number(100 * row[f"prob_aprobacion_{m}m"]) + "%" for m in HORIZON_MONTHS],
            ]
        )
    aj_24 = aj_summary.loc[aj_summary["horizonte_meses"].eq(24)]
    aj_rows = [
        [
            str(row["instrumento"]),
            EVENT_LABELS[str(row["outcome"])],
            _format_number(100 * row["incidencia_acumulada"]) + "%",
        ]
        for row in aj_24.to_dict("records")
    ]
    lines = [
        "# Resultados de supervivencia SEA",
        "",
        (
            f"Censura: **{SEA_DATA_CURRENCY_DATE:%d-%m-%Y}** (último registro; "
            f"descarga {SEA_DOWNLOAD_DATE:%d-%m-%Y}). Población: proyectos mineros "
            "admitidos a tramitación, sin inconsistencia de fechas y excluyendo "
            "tipologías i5* y nombres de áridos según la lista explícita, salvo "
            "tipologías i3 e i4 enviadas a revisión."
        ),
        "",
        "## Kaplan–Meier",
        "",
        (
            "**Tiempo hasta aprobación entre proyectos que siguen en juego.** Los "
            "desenlaces distintos de aprobación se tratan como censura; por eso estas "
            "probabilidades no son la cifra principal de probabilidad real de aprobación."
        ),
        "",
        _markdown_table(
            [
                "Instrumento",
                "Mediana KM (meses)",
                "IC 95%",
                "6 meses",
                "12 meses",
                "24 meses",
                "36 meses",
            ],
            km_rows,
        ),
        "",
        "## Riesgos competitivos (cifra principal)",
        "",
        (
            "La incidencia acumulada de Aalen–Johansen conserva desistimientos, "
            "rechazos y términos anticipados como desenlaces competidores. KM los "
            "censura y, en consecuencia, sobreestima la probabilidad de aprobación "
            "cuando estos riesgos existen."
        ),
        "",
        _markdown_table(["Instrumento", "Desenlace", "Incidencia a 24 meses"], aj_rows),
        "",
        "## Tendencia por cohorte de ingreso",
        "",
        (
            "La tendencia usa la mediana observada de duración exclusivamente entre "
            "proyectos aprobados. Las cohortes 2025–2026 se marcan como incompletas por "
            "censura y no deben interpretarse como una mejora reciente."
        ),
        "",
        f"Filas de tendencia: {len(trend)} (2011–2026 por instrumento).",
        "",
        "## Cox exploratorio",
        "",
    ]
    if cox is None or cox_metadata is None:
        lines.append(
            "No estimado: " + (cox_error or "el modelo no produjo un resultado válido.")
        )
    else:
        cox_rows = [
            [
                str(row["variable"]),
                _format_number(row["hazard_ratio"], 2),
                f"{_format_number(row['ic95_inf'], 2)}–{_format_number(row['ic95_sup'], 2)}",
                _format_number(row["p_value"], 3),
            ]
            for row in cox.to_dict("records")
        ]
        lines.extend(
            [
                _markdown_table(["Variable", "HR", "IC 95%", "p"], cox_rows),
                "",
                "Test de proporcionalidad de Schoenfeld (modelo inicial):",
                "",
                _markdown_table(
                    ["Variable", "p"],
                    [
                        [str(variable), _format_number(p_value, 3)]
                        for variable, p_value in cox_metadata["ph_pvalues"].items()
                    ],
                ),
                "",
                f"N={cox_metadata['n']}; aprobaciones={cox_metadata['eventos']}.",
                "El test de Schoenfeld "
                + (
                    (
                        "detectó una violación; el modelo se estratificó por instrumento, "
                        "pero persistieron violaciones en otras covariables."
                        if cox_metadata["ph_violated_after_stratification"]
                        else "detectó una violación; tras estratificar por instrumento no "
                        "quedaron violaciones al 5%."
                    )
                    if cox_metadata["stratified_by_instrument"]
                    else "no detectó violaciones al 5%."
                ),
            ]
        )
    lines.extend(
        [
            "",
            "## Supuestos y límites",
            "",
            (
                "- Las duraciones son días calendario desde ingreso hasta cierre; "
                "expedientes abiertos se censuran al 25-08-2026."
            ),
            (
                "- KM estima el tiempo hasta aprobación condicionado a seguir en juego; "
                "no es una probabilidad de cartera con riesgos competitivos."
            ),
            "- Aalen–Johansen es la estimación principal de incidencia acumulada por desenlace.",
            (
                "- El Cox es exploratorio y causa-específico; inversión faltante o no "
                "positiva se excluye del modelo."
            ),
            (
                "- Las medianas observadas de aprobados por cohorte sufren sesgo de "
                "selección, especialmente en 2025–2026."
            ),
            "",
            (
                "Fuente: Cochilco (dic-2025), SEA (descarga 30-09-2026; "
                "vigencia de datos 25-08-2026). Elaboración propia."
            ),
            "",
        ]
    )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text("\n".join(lines), encoding="utf-8")


def _cox_failure_types() -> tuple[type[BaseException], ...]:
    failures: list[type[BaseException]] = [
        RuntimeError,
        ValueError,
        np.linalg.LinAlgError,
        FloatingPointError,
    ]
    try:
        from lifelines.exceptions import ConvergenceError
    except ModuleNotFoundError:  # pragma: no cover - environment dependent
        pass
    else:
        failures.append(ConvergenceError)
    return tuple(failures)


def run_survival_analysis(
    sea_path: Path = SEA_PATH,
    output_dir: Path = PROCESSED_DIR,
    results_path: Path = RESULTS_PATH,
    exclusions_path: Path | None = None,
    exclusions_review_path: Path | None = None,
) -> dict[str, pd.DataFrame]:
    """Run every survival analysis and persist tidy data contracts."""
    sea_mining = pd.read_parquet(sea_path)
    population = build_survival_population(sea_mining)
    exclusions = build_population_exclusions(sea_mining)
    exclusions_review = build_population_exclusions_review(sea_mining)
    km_curve, km_summary = extract_km_tables(fit_kaplan_meier(population))
    aj_curve, aj_summary = extract_competing_risk_tables(fit_competing_risks(population))
    trend = build_trend_table(population)
    cox_error = None
    try:
        cox, cox_metadata = fit_cox_model(population)
    except _cox_failure_types() as error:
        cox, cox_metadata = None, None
        cox_error = str(error)

    output_dir.mkdir(parents=True, exist_ok=True)
    if exclusions_path is None:
        exclusions_path = results_path.parent / POPULATION_EXCLUSIONS_PATH.name
    if exclusions_review_path is None:
        exclusions_review_path = (
            results_path.parent / POPULATION_EXCLUSIONS_REVIEW_PATH.name
        )
    exclusions_path.parent.mkdir(parents=True, exist_ok=True)
    exclusions.to_csv(exclusions_path, index=False)
    exclusions_review_path.parent.mkdir(parents=True, exist_ok=True)
    exclusions_review.to_csv(exclusions_review_path, index=False)
    outputs = {
        "population": population,
        "km": km_curve,
        "km_summary": km_summary,
        "competing_risks": aj_curve,
        "competing_risks_summary": aj_summary,
        "trend": trend,
    }
    paths = {
        "population": POPULATION_PATH,
        "km": KM_PATH,
        "km_summary": KM_SUMMARY_PATH,
        "competing_risks": AJ_PATH,
        "competing_risks_summary": AJ_SUMMARY_PATH,
        "trend": TREND_PATH,
    }
    for name, frame in outputs.items():
        path = output_dir / paths[name].name
        frame.to_parquet(path, index=False)
    cox_path = output_dir / COX_PATH.name
    if cox is not None:
        cox.to_parquet(cox_path, index=False)
        outputs["cox"] = cox
    elif cox_path.exists():
        cox_path.unlink()
    write_results_markdown(
        km_summary,
        aj_summary,
        trend,
        cox,
        cox_metadata,
        cox_error=cox_error,
        output_path=results_path,
    )
    return outputs


def main() -> None:
    outputs = run_survival_analysis()
    print(f"Analyzed {len(outputs['population'])} admitted, date-consistent SEA projects")


if __name__ == "__main__":
    main()
