"""Independent numerical validation gate for brief-ready claims."""

from __future__ import annotations

import re
import unicodedata
import warnings
from collections.abc import Iterable, Mapping
from pathlib import Path
from statistics import NormalDist
from urllib.parse import quote_plus

import duckdb
import numpy as np
import pandas as pd

from cmip.config import PROCESSED_DIR, PROJECT_ROOT, SEIA_FICHA_URL
from cmip.survival import COMPETING_EVENT_CODES, DAYS_PER_MONTH

PORTFOLIO_PATH = PROCESSED_DIR / "cochilco_seia.parquet"
SEA_PATH = PROJECT_ROOT / "data" / "interim" / "sea_mining.parquet"
KM_SUMMARY_PATH = PROCESSED_DIR / "survival_km_summary.parquet"
AJ_SUMMARY_PATH = PROCESSED_DIR / "survival_competing_risks_summary.parquet"
SURVIVAL_POPULATION_PATH = PROCESSED_DIR / "survival_population.parquet"
CONFIRMED_MATCH_PATH = PROJECT_ROOT / "data" / "curated" / "cochilco_seia_match.csv"
CHECKLIST_PATH = PROJECT_ROOT / "docs" / "validation_checklist.csv"
CHECKLIST_ORPHANS_PATH = PROJECT_ROOT / "docs" / "validation_checklist_orphans.csv"

CLAIM_COLUMNS = [
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
ENVIRONMENTAL_STATES = [
    "aprobado",
    "en_evaluacion",
    "desistido_o_rechazado",
    "otro",
    "sin_expediente_en_ejecucion",
    "sin_expediente_en_estudio",
]
# Applied to an accent-stripped, case-folded expediente name. Word boundaries avoid
# unrelated substrings while singular/plural alternatives capture árido(s)/cantera(s).
QUARRY_NAME_REGEX = re.compile(r"\b(?:aridos?|canteras?)\b")


def _validated_event_arrays(
    durations: np.ndarray | pd.Series,
    events: np.ndarray | pd.Series,
) -> tuple[np.ndarray, np.ndarray]:
    duration_array = np.asarray(durations, dtype=float)
    event_array = np.asarray(events, dtype=int)
    if duration_array.ndim != 1 or event_array.ndim != 1:
        raise ValueError("durations and events must be one-dimensional")
    if len(duration_array) != len(event_array) or len(duration_array) == 0:
        raise ValueError("durations and events must have equal non-zero length")
    if not np.isfinite(duration_array).all() or (duration_array < 0).any():
        raise ValueError("durations must be finite and non-negative")
    return duration_array, event_array


def manual_kaplan_meier(
    durations: np.ndarray | pd.Series,
    event_observed: np.ndarray | pd.Series,
) -> pd.DataFrame:
    """Calculate a product-limit survival curve using only NumPy."""
    duration, observed = _validated_event_arrays(durations, event_observed)
    if not np.isin(observed, [0, 1]).all():
        raise ValueError("event_observed must contain only 0 and 1")

    survival = 1.0
    greenwood = 0.0
    z_value = NormalDist().inv_cdf(0.975)
    records = [(0.0, survival, 1.0, 1.0)]
    for time in np.unique(duration):
        at_risk = int(np.count_nonzero(duration >= time))
        events = int(np.count_nonzero((duration == time) & (observed == 1)))
        survival *= 1.0 - events / at_risk
        if events and at_risk > events:
            greenwood += events / (at_risk * (at_risk - events))
        if survival in {0.0, 1.0}:
            lower = upper = survival
        else:
            log_log = np.log(-np.log(survival))
            standard_error = np.sqrt(greenwood) / abs(np.log(survival))
            lower = np.exp(-np.exp(log_log + z_value * standard_error))
            upper = np.exp(-np.exp(log_log - z_value * standard_error))
        if time == 0:
            records[0] = (0.0, survival, lower, upper)
        else:
            records.append((float(time), survival, lower, upper))
    return pd.DataFrame(
        records,
        columns=[
            "time_days",
            "survival_probability",
            "survival_ci_lower",
            "survival_ci_upper",
        ],
    )


def manual_aalen_johansen(
    durations: np.ndarray | pd.Series,
    event_codes: np.ndarray | pd.Series,
    event_of_interest: int,
) -> pd.DataFrame:
    """Calculate an Aalen–Johansen cumulative-incidence curve using only NumPy."""
    duration, observed = _validated_event_arrays(durations, event_codes)
    if event_of_interest <= 0:
        raise ValueError("event_of_interest must be a positive event code")

    survival = 1.0
    incidence = 0.0
    records = [(0.0, incidence)]
    for time in np.unique(duration):
        at_risk = int(np.count_nonzero(duration >= time))
        target_events = int(
            np.count_nonzero((duration == time) & (observed == event_of_interest))
        )
        all_events = int(np.count_nonzero((duration == time) & (observed != 0)))
        incidence += survival * target_events / at_risk
        survival *= 1.0 - all_events / at_risk
        if time == 0:
            records[0] = (0.0, incidence)
        else:
            records.append((float(time), incidence))
    return pd.DataFrame(records, columns=["time_days", "cumulative_incidence"])


def claim_state(
    value: float | int,
    recalculated: float | int | None,
    tolerance: float,
) -> str:
    """Classify one candidate claim from its independently recalculated value."""
    if recalculated is None or pd.isna(recalculated):
        return "pendiente_J"
    value_float = float(value)
    recalculated_float = float(recalculated)
    if np.isinf(value_float) or np.isinf(recalculated_float):
        return (
            "verificada"
            if value_float == recalculated_float
            else "rechazada"
        )
    difference = abs(value_float - recalculated_float)
    return "verificada" if difference <= tolerance + 1e-12 else "rechazada"


def finalize_claims_register(rows: Iterable[Mapping[str, object]]) -> pd.DataFrame:
    """Apply tolerances and expose the stable claims-register schema."""
    records: list[dict[str, object]] = []
    for raw in rows:
        row = dict(raw)
        tolerance = float(row.pop("tolerancia"))
        value = float(row["valor"])
        recalculated = row.get("valor_recalculado")
        if recalculated is None or pd.isna(recalculated):
            difference = float("nan")
        elif value == float(recalculated):
            difference = 0.0
        else:
            difference = abs(value - float(recalculated))
        row["diferencia"] = difference
        row["estado"] = claim_state(value, recalculated, tolerance)
        records.append(row)
    result = pd.DataFrame(records, columns=CLAIM_COLUMNS)
    if result["claim_id"].duplicated().any():
        raise ValueError("claim_id values must be unique")
    return result


def _duckdb_frame(query: str, path: Path) -> pd.DataFrame:
    with duckdb.connect() as connection:
        return connection.execute(query, [str(path)]).fetchdf()


def _manual_population(sea: pd.DataFrame) -> pd.DataFrame:
    population = sea.loc[
        sea["admitido"].eq(True) & sea["fecha_inconsistente"].eq(False)
    ].copy()
    if population["duracion_dias"].isna().any():
        raise ValueError("Validation population contains missing durations")
    population["duration_days"] = population["duracion_dias"].astype(float).clip(lower=0.5)
    population["approval_event"] = population["evento"].eq("aprobado").astype(int)
    population["competing_event"] = (
        population["evento"].map(COMPETING_EVENT_CODES).fillna(0).astype(int)
    )
    return population.reset_index(drop=True)


def _first_crossing(curve: pd.DataFrame, column: str, threshold: float = 0.5) -> float:
    crossed = curve.loc[curve[column].le(threshold), "time_days"]
    return float(crossed.iloc[0]) if not crossed.empty else float("inf")


def _step_at(curve: pd.DataFrame, column: str, time_days: float) -> float:
    eligible = curve.loc[curve["time_days"].le(time_days), column]
    return float(eligible.iloc[-1]) if not eligible.empty else 0.0


def _normalized_name(value: object) -> str:
    normalized = unicodedata.normalize("NFKD", str(value).casefold())
    return "".join(character for character in normalized if not unicodedata.combining(character))


def _claim(
    claim_id: str,
    texto_es: str,
    valor: float | int,
    unidad: str,
    fuente: str,
    calculo: str,
    valor_recalculado: float | int,
    tolerancia: float,
    nota_semantica: str,
) -> dict[str, object]:
    return {
        "claim_id": claim_id,
        "texto_es": texto_es,
        "valor": valor,
        "unidad": unidad,
        "fuente": fuente,
        "calculo": calculo,
        "valor_recalculado": valor_recalculado,
        "tolerancia": tolerancia,
        "nota_semantica": nota_semantica,
    }


def build_claims_register(
    portfolio_path: Path = PORTFOLIO_PATH,
    sea_path: Path = SEA_PATH,
    km_summary_path: Path = KM_SUMMARY_PATH,
    aj_summary_path: Path = AJ_SUMMARY_PATH,
) -> pd.DataFrame:
    """Build and independently recalculate every candidate numeric brief claim."""
    for path in (portfolio_path, sea_path, km_summary_path, aj_summary_path):
        if not path.exists():
            raise FileNotFoundError(f"Required validation source is missing: {path}")

    portfolio = pd.read_parquet(portfolio_path)
    sea = pd.read_parquet(sea_path)
    km_summary_frame = pd.read_parquet(km_summary_path)
    aj_summary = pd.read_parquet(aj_summary_path)
    sources = {
        "portfolio": (portfolio, portfolio_path),
        "SEA": (sea, sea_path),
        "KM summary": (km_summary_frame, km_summary_path),
        "AJ summary": (aj_summary, aj_summary_path),
    }
    for label, (frame, path) in sources.items():
        if frame.empty:
            raise ValueError(f"{label} source is empty: {path}")
    km_summary = km_summary_frame.set_index("instrumento")
    population = _manual_population(sea)
    required_instruments = {"DIA", "EIA"}
    missing_population = required_instruments - set(population["instrumento"])
    missing_km = required_instruments - set(km_summary.index)
    required_aj = {
        (instrument, outcome)
        for instrument in required_instruments
        for outcome in COMPETING_EVENT_CODES
    }
    available_aj = set(zip(aj_summary["instrumento"], aj_summary["outcome"], strict=False))
    if missing_population:
        raise ValueError(
            "SEA validation population missing instruments: "
            f"{sorted(missing_population)}"
        )
    if missing_km:
        raise ValueError(f"KM summary missing instruments: {sorted(missing_km)}")
    if missing_aj := required_aj - available_aj:
        raise ValueError(f"AJ summary missing instrument/outcome groups: {sorted(missing_aj)}")
    rows: list[dict[str, object]] = []

    total = float(portfolio["inversion_musd"].sum())
    total_sql = float(
        _duckdb_frame(
            "SELECT SUM(inversion_musd) AS value FROM read_parquet(?)", portfolio_path
        ).loc[0, "value"]
    )
    rows.append(
        _claim(
            "cartera_inversion_total",
            "Inversión total de la cartera",
            total,
            "MMUS$",
            str(portfolio_path.relative_to(PROJECT_ROOT)),
            "Suma de inversión de los 59 proyectos Cochilco.",
            total_sql,
            0.1,
            "Monto nominal de cartera; no es inversión ejecutada ni ajustada por probabilidad.",
        )
    )

    environmental_sql = _duckdb_frame(
        """
        SELECT
          CASE
            WHEN exp_id_confirmado IS NULL AND etapa = 'Ejecución'
              THEN 'sin_expediente_en_ejecucion'
            WHEN exp_id_confirmado IS NULL THEN 'sin_expediente_en_estudio'
            WHEN evento = 'aprobado' THEN 'aprobado'
            WHEN evento = 'en_tramite' THEN 'en_evaluacion'
            WHEN evento IN ('desistido_o_abandonado', 'rechazado', 'termino_anticipado')
              THEN 'desistido_o_rechazado'
            ELSE 'otro'
          END AS estado_ambiental,
          COUNT(*) AS n,
          COALESCE(SUM(inversion_musd), 0) AS inversion_musd
        FROM read_parquet(?)
        GROUP BY 1
        """,
        portfolio_path,
    ).set_index("estado_ambiental")
    environmental_pipeline = portfolio.groupby("estado_ambiental", observed=True).agg(
        n=("project_id", "size"), inversion_musd=("inversion_musd", "sum")
    )
    for state in ENVIRONMENTAL_STATES:
        pipeline_n = (
            int(environmental_pipeline.loc[state, "n"])
            if state in environmental_pipeline.index
            else 0
        )
        pipeline_amount = (
            float(environmental_pipeline.loc[state, "inversion_musd"])
            if state in environmental_pipeline.index
            else 0.0
        )
        sql_n = int(environmental_sql.loc[state, "n"]) if state in environmental_sql.index else 0
        sql_amount = (
            float(environmental_sql.loc[state, "inversion_musd"])
            if state in environmental_sql.index
            else 0.0
        )
        semantic = (
            "Sin expediente confirmado y etapa Cochilco Ejecución."
            if state == "sin_expediente_en_ejecucion"
            else "Sin expediente confirmado y etapa distinta de Ejecución."
            if state == "sin_expediente_en_estudio"
            else "Estado basado en el desenlace del expediente SEA confirmado."
        )
        rows.extend(
            [
                _claim(
                    f"estado_{state}_n",
                    f"Proyectos en estado ambiental {state}",
                    pipeline_n,
                    "proyectos",
                    str(portfolio_path.relative_to(PROJECT_ROOT)),
                    "Conteo por estado ambiental.",
                    sql_n,
                    0.0,
                    semantic,
                ),
                _claim(
                    f"estado_{state}_inversion",
                    f"Inversión en estado ambiental {state}",
                    pipeline_amount,
                    "MMUS$",
                    str(portfolio_path.relative_to(PROJECT_ROOT)),
                    "Suma de inversión por estado ambiental.",
                    sql_amount,
                    0.1,
                    semantic,
                ),
            ]
        )

    for instrument in ("DIA", "EIA"):
        group = population.loc[population["instrumento"].eq(instrument)]
        curve = manual_kaplan_meier(group["duration_days"], group["approval_event"])
        manual_values = {
            "mediana": _first_crossing(curve, "survival_probability") / DAYS_PER_MONTH,
            "ic95_inf": _first_crossing(curve, "survival_ci_lower") / DAYS_PER_MONTH,
            "ic95_sup": _first_crossing(curve, "survival_ci_upper") / DAYS_PER_MONTH,
        }
        pipeline_values = {
            "mediana": float(km_summary.loc[instrument, "mediana_km_meses"]),
            "ic95_inf": float(km_summary.loc[instrument, "mediana_ic95_inf_meses"]),
            "ic95_sup": float(km_summary.loc[instrument, "mediana_ic95_sup_meses"]),
        }
        labels = {
            "mediana": "Mediana KM",
            "ic95_inf": "Límite inferior IC 95% de la mediana KM",
            "ic95_sup": "Límite superior IC 95% de la mediana KM",
        }
        for statistic in ("mediana", "ic95_inf", "ic95_sup"):
            rows.append(
                _claim(
                    f"km_{instrument}_{statistic}",
                    f"{labels[statistic]} {instrument}",
                    pipeline_values[statistic],
                    "meses",
                    str(km_summary_path.relative_to(PROJECT_ROOT)),
                    "Producto límite; desenlaces no aprobados censurados.",
                    manual_values[statistic],
                    0.1,
                    "KM mide aprobación condicionada a seguir en juego; no probabilidad "
                    "real con riesgos competitivos.",
                )
            )

    aj_24 = aj_summary.loc[aj_summary["horizonte_meses"].eq(24)].set_index(
        ["instrumento", "outcome"]
    )
    for instrument in ("DIA", "EIA"):
        group = population.loc[population["instrumento"].eq(instrument)]
        for outcome, code in COMPETING_EVENT_CODES.items():
            curve = manual_aalen_johansen(
                group["duration_days"], group["competing_event"], code
            )
            recalculated = 100 * _step_at(
                curve, "cumulative_incidence", 24 * DAYS_PER_MONTH
            )
            value = 100 * float(aj_24.loc[(instrument, outcome), "incidencia_acumulada"])
            rows.append(
                _claim(
                    f"aj_{instrument}_{outcome}_24m",
                    f"Incidencia acumulada a 24 meses: {outcome}, {instrument}",
                    value,
                    "%",
                    str(aj_summary_path.relative_to(PROJECT_ROOT)),
                    "Aalen–Johansen con los otros desenlaces como riesgos competitivos.",
                    recalculated,
                    0.5,
                    "Incidencia acumulada marginal; conserva todos los desenlaces competidores.",
                )
            )

    eia_mask = portfolio["instrumento"].eq("EIA") & portfolio["evento"].eq("en_tramite")
    eia_n = int(eia_mask.sum())
    eia_amount = float(portfolio.loc[eia_mask, "inversion_musd"].sum())
    eia_sql = _duckdb_frame(
        """
        SELECT COUNT(*) AS n, COALESCE(SUM(inversion_musd), 0) AS inversion_musd
        FROM read_parquet(?)
        WHERE instrumento = 'EIA' AND evento = 'en_tramite'
        """,
        portfolio_path,
    ).iloc[0]
    rows.extend(
        [
            _claim(
                "eia_en_evaluacion_n",
                "EIA de la cartera en evaluación hoy",
                eia_n,
                "proyectos",
                str(portfolio_path.relative_to(PROJECT_ROOT)),
                "Conteo de EIA confirmadas con evento en_tramite.",
                int(eia_sql["n"]),
                0.0,
                "Hoy corresponde al corte SEA 30-09-2026, no a tiempo real.",
            ),
            _claim(
                "eia_en_evaluacion_inversion",
                "Inversión de EIA de la cartera en evaluación hoy",
                eia_amount,
                "MMUS$",
                str(portfolio_path.relative_to(PROJECT_ROOT)),
                "Suma de inversión de EIA confirmadas con evento en_tramite.",
                float(eia_sql["inversion_musd"]),
                0.1,
                "Hoy corresponde al corte SEA 30-09-2026, no a tiempo real.",
            ),
        ]
    )
    return finalize_claims_register(rows)


def build_sensitivity_table(
    population_path: Path = SURVIVAL_POPULATION_PATH,
) -> pd.DataFrame:
    """Calculate KM medians and 24-month approval CIF for four SEA segments."""
    population = pd.read_parquet(population_path).copy()
    population["duration_days"] = population["duration_days"].astype(float).clip(lower=0.5)
    normalized_names = population["exp_nombre"].map(_normalized_name)
    not_quarry = ~normalized_names.str.contains(QUARRY_NAME_REGEX, regex=True)
    segments = {
        "Todos": pd.Series(True, index=population.index),
        ">=100 MMUS$": population["inversion_musd"].ge(100),
        "<100 MMUS$": population["inversion_musd"].lt(100),
        "Sin áridos/canteras": not_quarry,
    }
    rows: list[dict[str, object]] = []
    for segment, segment_mask in segments.items():
        for instrument in ("DIA", "EIA"):
            group = population.loc[segment_mask & population["instrumento"].eq(instrument)]
            km = manual_kaplan_meier(group["duration_days"], group["approval_event"])
            aj = manual_aalen_johansen(
                group["duration_days"], group["competing_event"], event_of_interest=1
            )
            rows.append(
                {
                    "segmento": segment,
                    "instrumento": instrument,
                    "n": len(group),
                    "mediana_km_meses": _first_crossing(km, "survival_probability")
                    / DAYS_PER_MONTH,
                    "incidencia_aprobacion_24m_pct": 100
                    * _step_at(aj, "cumulative_incidence", 24 * DAYS_PER_MONTH),
                }
            )
    return pd.DataFrame(rows)


def bootstrap_eia_high_investment_approval_24m(
    population_path: Path = SURVIVAL_POPULATION_PATH,
    replicas: int = 1000,
    seed: int = 20261002,
) -> pd.DataFrame:
    """Bootstrap the EIA >=100 MMUS$ 24-month approval cumulative incidence."""
    population = pd.read_parquet(population_path)
    group = population.loc[
        population["instrumento"].eq("EIA") & population["inversion_musd"].ge(100)
    ].copy()
    group["duration_days"] = group["duration_days"].astype(float).clip(lower=0.5)
    if group.empty:
        raise ValueError("No EIA >=100 MMUS$ records available for bootstrap")
    rng = np.random.default_rng(seed)

    def estimate(frame: pd.DataFrame) -> float:
        curve = manual_aalen_johansen(
            frame["duration_days"], frame["competing_event"], event_of_interest=1
        )
        return 100 * _step_at(curve, "cumulative_incidence", 24 * DAYS_PER_MONTH)

    estimates = np.empty(replicas, dtype=float)
    for replica in range(replicas):
        sample_positions = rng.integers(0, len(group), size=len(group))
        estimates[replica] = estimate(group.iloc[sample_positions])
    lower, upper = np.quantile(estimates, [0.025, 0.975])
    return pd.DataFrame(
        [
            {
                "segmento": ">=100 MMUS$",
                "instrumento": "EIA",
                "n": len(group),
                "replicas": replicas,
                "semilla": seed,
                "estimacion_pct": estimate(group),
                "ic95_inf_pct": float(lower),
                "ic95_sup_pct": float(upper),
            }
        ]
    )


def build_validation_checklist(
    portfolio_path: Path = PORTFOLIO_PATH,
    sea_path: Path = SEA_PATH,
    confirmed_match_path: Path = CONFIRMED_MATCH_PATH,
    checklist_path: Path | None = CHECKLIST_PATH,
    orphans_path: Path | None = CHECKLIST_ORPHANS_PATH,
) -> pd.DataFrame:
    """Build J's obligations, retaining prior answers and archiving removed IDs."""
    portfolio = pd.read_parquet(portfolio_path)
    sea = pd.read_parquet(sea_path).set_index("exp_id")
    decisions = pd.read_csv(confirmed_match_path)
    decision_ids = decisions.loc[decisions["criterio"].eq("decision_J"), "cochilco_id"]
    portfolio_by_id = portfolio.set_index("project_id", drop=False)
    missing_decisions = set(decision_ids) - set(portfolio_by_id.index)
    if missing_decisions:
        raise ValueError(f"decision_J projects missing from portfolio: {sorted(missing_decisions)}")

    def checklist_row(
        project: pd.Series, question: str, group_order: int
    ) -> dict[str, object]:
        exp_id = project["exp_id_confirmado"]
        sea_name = ""
        expediente_url = ""
        if pd.notna(exp_id):
            numeric_id = int(exp_id)
            if numeric_id not in sea.index:
                raise ValueError(f"Confirmed exp_id missing from SEA source: {numeric_id}")
            sea_name = str(sea.loc[numeric_id, "exp_nombre"])
            expediente_url = SEIA_FICHA_URL.format(exp_id=numeric_id)
        cochilco_name = str(project["nombre_del_proyecto"])
        encoded_query = quote_plus(f'site:seia.sea.gob.cl "{cochilco_name}"')
        return {
            "cochilco_id": project["project_id"],
            "cochilco_nombre": cochilco_name,
            "empresa": project["empresa"],
            "etapa": project["etapa"],
            "inversion_musd": project["inversion_musd"],
            "exp_id_confirmado": exp_id,
            "sea_nombre": sea_name,
            "url_expediente": expediente_url,
            "url_busqueda": f"https://www.google.com/search?q={encoded_query}",
            "pregunta": question,
            "respuesta_J": "",
            "fuente_J": "",
            "_group_order": group_order,
        }

    rows: list[dict[str, object]] = []
    for cochilco_id in decision_ids:
        project = portfolio_by_id.loc[cochilco_id]
        question = (
            "¿El expediente corresponde a este proyecto y a esta fase?"
            if pd.notna(project["exp_id_confirmado"])
            else (
                "¿Existe expediente propio 2011-2026 o el proyecto usa una RCA previa "
                "o una consulta de pertinencia?"
            )
        )
        group_order = 1 if pd.notna(project["exp_id_confirmado"]) else 2
        rows.append(checklist_row(project, question, group_order))

    execution = portfolio.loc[
        portfolio["exp_id_confirmado"].isna() & portfolio["etapa"].eq("Ejecución")
    ]
    if len(execution) != 6:
        raise ValueError(
            f"Expected six missing-expediente execution projects, found {len(execution)}"
        )
    for _, project in execution.iterrows():
        rows.append(
            checklist_row(
                project, "¿N° de RCA vigente que cubre la ejecución?", group_order=0
            )
        )

    columns = [
        "cochilco_id",
        "cochilco_nombre",
        "empresa",
        "etapa",
        "inversion_musd",
        "exp_id_confirmado",
        "sea_nombre",
        "url_expediente",
        "url_busqueda",
        "pregunta",
        "respuesta_J",
        "fuente_J",
    ]
    result = (
        pd.DataFrame(rows)
        .sort_values(
            ["_group_order", "inversion_musd", "cochilco_id"],
            ascending=[True, False, True],
            kind="stable",
        )
        .drop(columns="_group_order")
        .reset_index(drop=True)
    )
    result = result.loc[:, columns]
    if checklist_path is not None and checklist_path.exists():
        existing = pd.read_csv(checklist_path, keep_default_na=False)
        result = _preserve_j_responses(result, existing)
        _archive_checklist_orphans(result, existing, orphans_path)
    return result


def _nonempty_text(value: object) -> str:
    if value is None or pd.isna(value):
        return ""
    return str(value).strip()


def _preserve_j_responses(
    checklist: pd.DataFrame, existing: pd.DataFrame
) -> pd.DataFrame:
    """Retain J fields by obligation, falling back to the requested project ID key."""
    result = checklist.copy()
    if "cochilco_id" not in existing:
        raise ValueError("Existing validation checklist has no cochilco_id column")
    for column in ("pregunta", "respuesta_J", "fuente_J"):
        if column not in existing:
            existing[column] = ""
    for index, row in result.iterrows():
        same_id = existing.loc[
            existing["cochilco_id"].astype(str).eq(str(row["cochilco_id"]))
        ]
        exact = same_id.loc[same_id["pregunta"].astype(str).eq(str(row["pregunta"]))]
        candidates = exact if not exact.empty else same_id
        for column in ("respuesta_J", "fuente_J"):
            saved = [text for text in candidates[column].map(_nonempty_text) if text]
            if saved:
                result.at[index, column] = saved[0]
    return result


def _write_csv_atomically(frame: pd.DataFrame, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = path.with_suffix(path.suffix + ".tmp")
    frame.to_csv(temporary_path, index=False)
    temporary_path.replace(path)


def _archive_checklist_orphans(
    checklist: pd.DataFrame,
    existing: pd.DataFrame,
    orphans_path: Path | None,
) -> None:
    current_ids = set(checklist["cochilco_id"].astype(str))
    orphans = existing.loc[~existing["cochilco_id"].astype(str).isin(current_ids)].copy()
    if orphans.empty:
        return
    orphan_ids = sorted(orphans["cochilco_id"].astype(str).unique())
    warnings.warn(
        f"Checklist projects no longer present; archived as orphans: {orphan_ids}",
        UserWarning,
        stacklevel=3,
    )
    if orphans_path is None:
        return
    if orphans_path.exists():
        archived = pd.read_csv(orphans_path, keep_default_na=False)
        orphans = pd.concat([archived, orphans], ignore_index=True, sort=False)
        dedupe_columns = [
            column
            for column in ("cochilco_id", "pregunta", "respuesta_J", "fuente_J")
            if column in orphans
        ]
        orphans = orphans.drop_duplicates(dedupe_columns, keep="last")
    _write_csv_atomically(orphans, orphans_path)


def write_validation_checklist(
    portfolio_path: Path = PORTFOLIO_PATH,
    sea_path: Path = SEA_PATH,
    confirmed_match_path: Path = CONFIRMED_MATCH_PATH,
    checklist_path: Path = CHECKLIST_PATH,
    orphans_path: Path = CHECKLIST_ORPHANS_PATH,
) -> pd.DataFrame:
    """Regenerate the checklist without discarding J responses or removed projects."""
    result = build_validation_checklist(
        portfolio_path,
        sea_path,
        confirmed_match_path,
        checklist_path=checklist_path,
        orphans_path=orphans_path,
    )
    _write_csv_atomically(result, checklist_path)
    return result


def main() -> None:
    """Print validation artifacts for review without overwriting J's checklist."""
    claims = build_claims_register()
    sensitivity = build_sensitivity_table()
    bootstrap = bootstrap_eia_high_investment_approval_24m()
    checklist = write_validation_checklist()
    answered = int(checklist["respuesta_J"].astype(str).str.strip().ne("").sum())
    print("\nRegistro de cifras\n", claims.to_string(index=False))
    print("\nSensibilidad\n", sensitivity.to_string(index=False))
    print("\nBootstrap\n", bootstrap.to_string(index=False))
    print(f"\nChecklist: {answered} / {len(checklist)} respondidas")


if __name__ == "__main__":
    main()
