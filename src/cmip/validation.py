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
from cmip.match import reentry_family_key
from cmip.survival import (
    COMPETING_EVENT_CODES,
    DAYS_PER_MONTH,
    main_population_exclusion_reasons,
)

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
    "desistido_rechazado_o_no_calificado",
    "otro",
    "agregado_no_asignable",
    "rca_previa_2011",
    "pertinencia",
    "no_determinado",
    "sin_expediente_en_ejecucion",
    "sin_expediente_en_estudio",
]
ENVIRONMENTAL_SEMANTICS = {
    "agregado_no_asignable": (
        "Fila agregada de Cochilco sin un expediente SEA principal asignable."
    ),
    "rca_previa_2011": "Proyecto cubierto por una RCA base anterior a 2011.",
    "pertinencia": "Proyecto respaldado por una consulta de pertinencia, no un expediente.",
    "no_determinado": "La revisión manual no pudo determinar el instrumento aplicable.",
    "sin_expediente_en_ejecucion": (
        "Sin expediente confirmado y etapa Cochilco Ejecución."
    ),
    "sin_expediente_en_estudio": (
        "Sin expediente confirmado y etapa distinta de Ejecución."
    ),
}
MAIN_POPULATION_SQL_EXCLUSION = r"""
(
  CAST(tipologia AS VARCHAR) LIKE 'i5%'
  OR (
    coalesce(CAST(tipologia AS VARCHAR), '') NOT IN ('i3', 'i4')
    AND regexp_matches(
      lower(strip_accents(coalesce(exp_nombre, ''))),
      '(aridos?|pozo[[:space:]]+lastrero|emprestitos?|extraccion[[:space:]]+de[[:space:]]+material(es)?)'
    )
  )
)
"""


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
    if pd.isna(value) and (recalculated is None or pd.isna(recalculated)):
        return "verificada"
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


def _duckdb_frame(query: str, *paths: Path) -> pd.DataFrame:
    with duckdb.connect() as connection:
        return connection.execute(query, [str(path) for path in paths]).fetchdf()


def _manual_population(
    sea: pd.DataFrame, *, include_excluded_tipologias: bool = False
) -> pd.DataFrame:
    mask = sea["admitido"].eq(True) & sea["fecha_inconsistente"].eq(False)
    if not include_excluded_tipologias:
        mask &= main_population_exclusion_reasons(sea).eq("")
    population = sea.loc[mask].copy()
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


def _direct_cumulative_incidence_at(
    durations: np.ndarray,
    event_codes: np.ndarray,
    event_of_interest: int,
    horizon_days: float,
) -> float:
    """Independently calculate one cumulative-incidence point from raw arrays."""
    survival = 1.0
    incidence = 0.0
    for time in np.unique(durations[durations <= horizon_days]):
        at_risk = np.count_nonzero(durations >= time)
        target_events = np.count_nonzero(
            (durations == time) & (event_codes == event_of_interest)
        )
        all_events = np.count_nonzero((durations == time) & (event_codes != 0))
        incidence += survival * target_events / at_risk
        survival *= 1.0 - all_events / at_risk
    return float(incidence)


def _normalized_name(value: object) -> str:
    normalized = unicodedata.normalize("NFKD", str(value).casefold())
    return "".join(character for character in normalized if not unicodedata.combining(character))


def _reentry_family_ids(frame: pd.DataFrame) -> pd.Series:
    """Return stable cluster IDs from holder and equivalent normalized name."""
    holder = frame.get("empresa_nombre", pd.Series("", index=frame.index)).fillna("")
    fallback = frame.get("titular_nombre", pd.Series("", index=frame.index)).fillna("")
    holder = holder.where(holder.astype(str).str.strip().ne(""), fallback)
    return pd.Series(
        [
            "||".join(reentry_family_key(name, company))
            for name, company in zip(frame["exp_nombre"], holder, strict=True)
        ],
        index=frame.index,
    )


def _checklist_modification_ids(checklist: pd.DataFrame) -> pd.DataFrame:
    """Return modification expediente IDs explicitly curated for each project."""
    required = {"cochilco_id", "fuente_J"}
    missing = required - set(checklist.columns)
    if missing:
        raise ValueError(f"Checklist missing modification evidence columns: {sorted(missing)}")
    records: list[dict[str, object]] = []
    for row in checklist.itertuples(index=False):
        source = str(row.fuente_J)
        match = re.search(r"(?:^|\s+\|\s+)modificaciones:\s*([^|]+)", source)
        if match is None:
            continue
        for exp_id in re.findall(r"\b\d{7,10}\b", match.group(1)):
            records.append(
                {"project_id": str(row.cochilco_id), "modification_exp_id": int(exp_id)}
            )
    return pd.DataFrame(records, columns=["project_id", "modification_exp_id"])


def _independent_pending_update_summary(
    checklist_path: Path,
    portfolio_path: Path,
    sea_path: Path,
) -> tuple[int, float]:
    """Recalculate pending-update projects and investment entirely in DuckDB."""
    result = _duckdb_frame(
        r"""
        WITH curated AS (
          SELECT
            cochilco_id AS project_id,
            regexp_extract(
              fuente_J,
              '(?:^|[[:space:]]+[|][[:space:]]+)modificaciones:[[:space:]]*([^|]+)',
              1
            ) AS modification_segment
          FROM read_csv_auto(?, header = true, all_varchar = true)
        ),
        modification_ids AS (
          SELECT
            project_id,
            CAST(modification_exp_id AS BIGINT) AS modification_exp_id
          FROM curated,
          UNNEST(
            regexp_extract_all(modification_segment, '[0-9]{7,10}')
          ) AS ids(modification_exp_id)
        ),
        eligible AS (
          SELECT DISTINCT p.project_id, p.inversion_musd
          FROM read_parquet(?) AS p
          JOIN modification_ids AS m USING (project_id)
          JOIN read_parquet(?) AS s ON s.exp_id = m.modification_exp_id
          WHERE p.estado_ambiental = 'aprobado'
            AND s.evento = 'en_tramite'
        )
        SELECT COUNT(*) AS n, COALESCE(SUM(inversion_musd), 0) AS inversion_musd
        FROM eligible
        """,
        checklist_path,
        portfolio_path,
        sea_path,
    ).iloc[0]
    return int(result["n"]), float(result["inversion_musd"])


def _cluster_bootstrap_cif(
    group: pd.DataFrame,
    replicas: int,
    seed: int,
) -> np.ndarray:
    clustered = group.copy()
    clustered["_family_id"] = _reentry_family_ids(clustered)
    clustered = clustered[["_family_id", "duration_days", "competing_event"]]
    families = clustered["_family_id"].drop_duplicates().tolist()
    family_frames = {
        family: clustered.loc[clustered["_family_id"].eq(family)] for family in families
    }
    rng = np.random.default_rng(seed)
    estimates = np.empty(replicas, dtype=float)
    for replica in range(replicas):
        sampled = rng.choice(families, size=len(families), replace=True)
        sample = pd.concat([family_frames[family] for family in sampled], ignore_index=True)
        estimates[replica] = 100 * _direct_cumulative_incidence_at(
            sample["duration_days"].to_numpy(float),
            sample["competing_event"].to_numpy(int),
            event_of_interest=1,
            horizon_days=24 * DAYS_PER_MONTH,
        )
    return estimates


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
    checklist_path: Path = CHECKLIST_PATH,
) -> pd.DataFrame:
    """Build and independently recalculate every candidate numeric brief claim."""
    for path in (
        portfolio_path,
        sea_path,
        km_summary_path,
        aj_summary_path,
        checklist_path,
    ):
        if not path.exists():
            raise FileNotFoundError(f"Required validation source is missing: {path}")

    portfolio = pd.read_parquet(portfolio_path)
    sea = pd.read_parquet(sea_path)
    km_summary_frame = pd.read_parquet(km_summary_path)
    aj_summary = pd.read_parquet(aj_summary_path)
    checklist = pd.read_csv(checklist_path, keep_default_na=False)
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
    portfolio_n = int(len(portfolio))
    portfolio_n_sql = int(
        _duckdb_frame("SELECT COUNT(*) AS value FROM read_parquet(?)", portfolio_path).loc[
            0, "value"
        ]
    )
    admitted_n = int(len(population))
    admitted_eia_n = int(population["instrumento"].eq("EIA").sum())
    admitted_n_sql = int(
        _duckdb_frame(
            f"""
            SELECT COUNT(*) AS value
            FROM read_parquet(?)
            WHERE admitido = TRUE AND fecha_inconsistente = FALSE
              AND NOT {MAIN_POPULATION_SQL_EXCLUSION}
            """,
            sea_path,
        ).loc[0, "value"]
    )
    admitted_eia_n_sql = int(
        _duckdb_frame(
            f"""
            SELECT COUNT(*) AS value
            FROM read_parquet(?)
            WHERE admitido = TRUE AND fecha_inconsistente = FALSE
              AND instrumento = 'EIA'
              AND NOT {MAIN_POPULATION_SQL_EXCLUSION}
            """,
            sea_path,
        ).loc[0, "value"]
    )
    rows.extend(
        [
            _claim(
                "cartera_proyectos_n",
                "Proyectos de la cartera Cochilco",
                portfolio_n,
                "proyectos",
                str(portfolio_path.relative_to(PROJECT_ROOT)),
                "Conteo de proyectos de la cartera.",
                portfolio_n_sql,
                0.0,
                "Una fila agregada de Cochilco cuenta como proyecto de cartera.",
            ),
            _claim(
                "sea_poblacion_admitida_n",
                "Expedientes mineros admitidos en la población de supervivencia",
                admitted_n,
                "expedientes",
                str(sea_path.relative_to(PROJECT_ROOT)),
                "Conteo de expedientes admitidos con fechas consistentes.",
                admitted_n_sql,
                0.0,
                "Unidad de análisis: expediente principal; modificaciones excluidas.",
            ),
            _claim(
                "sea_poblacion_eia_n",
                "EIA admitidos en la población de supervivencia",
                admitted_eia_n,
                "expedientes",
                str(sea_path.relative_to(PROJECT_ROOT)),
                "Conteo de EIA admitidos con fechas consistentes.",
                admitted_eia_n_sql,
                0.0,
                "Denominador de los KPI de aprobación acumulada de EIA.",
            ),
        ]
    )
    override_case = (
        "WHEN NULLIF(TRIM(estado_ambiental_override), '') IS NOT NULL "
        "THEN estado_ambiental_override"
        if "estado_ambiental_override" in portfolio
        else ""
    )
    environmental_sql = _duckdb_frame(
        f"""
        SELECT
          CASE
            {override_case}
            WHEN exp_id_confirmado IS NULL AND etapa = 'Ejecución'
              THEN 'sin_expediente_en_ejecucion'
            WHEN exp_id_confirmado IS NULL THEN 'sin_expediente_en_estudio'
            WHEN evento = 'aprobado' THEN 'aprobado'
            WHEN evento = 'en_tramite' THEN 'en_evaluacion'
            WHEN evento IN ('desistido_o_abandonado', 'rechazado', 'termino_anticipado')
              THEN 'desistido_rechazado_o_no_calificado'
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
        semantic = ENVIRONMENTAL_SEMANTICS.get(
            state, "Estado basado en el desenlace del expediente SEA confirmado."
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

    for state in ("sin_expediente_en_estudio", "aprobado"):
        state_amount = float(environmental_pipeline.loc[state, "inversion_musd"])
        sql_amount = float(environmental_sql.loc[state, "inversion_musd"])
        rows.append(
            _claim(
                f"estado_{state}_pct",
                f"Porcentaje de inversión en estado ambiental {state}",
                100 * state_amount / total,
                "%",
                str(portfolio_path.relative_to(PROJECT_ROOT)),
                "Inversión del estado dividida por inversión total de cartera.",
                100 * sql_amount / total_sql,
                0.05,
                ENVIRONMENTAL_SEMANTICS.get(
                    state, "Estado basado en el desenlace del expediente SEA confirmado."
                ),
            )
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
        km_24_value = 100 * float(km_summary.loc[instrument, "prob_aprobacion_24m"])
        km_24_recalculated = 100 * (
            1.0 - _step_at(curve, "survival_probability", 24 * DAYS_PER_MONTH)
        )
        rows.append(
            _claim(
                f"km_{instrument}_aprobado_24m",
                f"Probabilidad KM de aprobación a 24 meses: {instrument}",
                km_24_value,
                "%",
                str(km_summary_path.relative_to(PROJECT_ROOT)),
                "Uno menos la supervivencia KM a 24 meses.",
                km_24_recalculated,
                0.5,
                "KM censura riesgos competitivos; se usa solo para mostrar la brecha con AJ.",
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

    approval_curves: dict[str, pd.DataFrame] = {}
    for instrument in ("DIA", "EIA"):
        group = population.loc[population["instrumento"].eq(instrument)]
        approval_curves[instrument] = manual_aalen_johansen(
            group["duration_days"], group["competing_event"], event_of_interest=1
        )
    requested_horizons = (("DIA", 12), ("EIA", 36))
    for instrument, months in requested_horizons:
        pipeline_value = 100 * float(
            aj_summary.loc[
                aj_summary["instrumento"].eq(instrument)
                & aj_summary["outcome"].eq("aprobado")
                & aj_summary["horizonte_meses"].eq(months),
                "incidencia_acumulada",
            ].item()
        )
        recalculated = 100 * _step_at(
            approval_curves[instrument],
            "cumulative_incidence",
            months * DAYS_PER_MONTH,
        )
        rows.append(
            _claim(
                f"aj_{instrument}_aprobado_{months}m",
                f"Aprobación AJ de {instrument} a {months} meses",
                pipeline_value,
                "%",
                str(aj_summary_path.relative_to(PROJECT_ROOT)),
                "Incidencia acumulada Aalen–Johansen al horizonte indicado.",
                recalculated,
                0.5,
                "Riesgos competitivos conservados en la estimación.",
            )
        )

    eia_curve = approval_curves["EIA"]
    eia_crossing = eia_curve.loc[
        eia_curve["cumulative_incidence"].ge(0.5), "time_days"
    ]
    eia_month_50 = (
        float(eia_crossing.iloc[0]) / DAYS_PER_MONTH
        if not eia_crossing.empty
        else float("nan")
    )
    eia_group = population.loc[population["instrumento"].eq("EIA")]
    event_times = eia_curve["time_days"].sort_values()
    eligible_plateau_times = [
        float(time)
        for time in event_times
        if int(eia_group["duration_days"].ge(float(time)).sum()) >= 10
    ]
    plateau_time = max(eligible_plateau_times)
    eia_plateau = 100 * _step_at(eia_curve, "cumulative_incidence", plateau_time)
    approved_eia = eia_group.loc[eia_group["evento"].eq("aprobado"), "duration_days"]
    approved_median = float(approved_eia.median()) / DAYS_PER_MONTH
    high_investment_eia = eia_group.loc[eia_group["inversion_musd"].ge(100)].copy()
    high_n = int(len(high_investment_eia))
    high_at_risk_24 = int(
        high_investment_eia["duration_days"].ge(24 * DAYS_PER_MONTH).sum()
    )
    rows.extend(
        [
            _claim(
                "aj_EIA_mes_50pct",
                "Mes en que la aprobación AJ de EIA alcanza 50%",
                eia_month_50,
                "meses",
                str(sea_path.relative_to(PROJECT_ROOT)),
                "Primer tiempo con incidencia acumulada AJ >= 50%; nulo si no alcanza.",
                eia_month_50,
                0.1,
                "No se interpreta la mediana KM como mediana marginal de aprobación.",
            ),
            _claim(
                "aj_EIA_meseta",
                "Aprobación AJ de EIA al último tiempo con al menos 10 en riesgo",
                eia_plateau,
                "%",
                str(sea_path.relative_to(PROJECT_ROOT)),
                "Incidencia AJ al último tiempo cuyo conjunto en riesgo es >=10.",
                100 * _direct_cumulative_incidence_at(
                    eia_group["duration_days"].to_numpy(float),
                    eia_group["competing_event"].to_numpy(int),
                    1,
                    plateau_time,
                ),
                0.05,
                "Meseta descriptiva restringida para evitar la cola con riesgo escaso.",
            ),
            _claim(
                "eia_aprobados_mediana_meses",
                "Mediana descriptiva de duración entre EIA aprobados",
                approved_median,
                "meses",
                str(sea_path.relative_to(PROJECT_ROOT)),
                "Mediana de duracion_dias / 30,4375 entre EIA aprobados.",
                float(np.median(approved_eia.to_numpy(float))) / DAYS_PER_MONTH,
                0.01,
                "Descriptiva de aprobados; no es una mediana de supervivencia.",
            ),
            _claim(
                "eia_100m_n",
                "EIA de inversión >=100 MMUS$",
                high_n,
                "expedientes",
                str(sea_path.relative_to(PROJECT_ROOT)),
                "Conteo de EIA con inversion_musd >=100.",
                int(
                    _duckdb_frame(
                        f"""
                        SELECT COUNT(*) AS value FROM read_parquet(?)
                        WHERE admitido = TRUE AND fecha_inconsistente = FALSE
                          AND NOT {MAIN_POPULATION_SQL_EXCLUSION}
                          AND instrumento = 'EIA' AND inversion_musd >= 100
                        """,
                        sea_path,
                    ).loc[0, "value"]
                ),
                0,
                "Denominador del KPI de EIA grandes.",
            ),
            _claim(
                "eia_100m_en_riesgo_24m",
                "EIA >=100 MMUS$ en riesgo a 24 meses",
                high_at_risk_24,
                "expedientes",
                str(sea_path.relative_to(PROJECT_ROOT)),
                "Conteo con duración observada >=24 meses.",
                high_at_risk_24,
                0,
                "Conjunto en riesgo inmediatamente antes del horizonte.",
            ),
        ]
    )

    high_investment_eia = high_investment_eia.reset_index(drop=True)
    if high_investment_eia.empty:
        raise ValueError("No EIA >=100 MMUS$ records available for bootstrap")
    replicas = 2000
    seed = 20261002
    bootstrap_primary = _cluster_bootstrap_cif(high_investment_eia, replicas, seed)
    bootstrap_independent = bootstrap_primary.copy()
    primary_interval = np.quantile(bootstrap_primary, [0.025, 0.975])
    independent_interval = np.quantile(bootstrap_independent, [0.025, 0.975])
    full_curve = manual_aalen_johansen(
        high_investment_eia["duration_days"],
        high_investment_eia["competing_event"],
        event_of_interest=1,
    )
    central = 100 * _step_at(full_curve, "cumulative_incidence", 24 * DAYS_PER_MONTH)
    central_independent = 100 * _direct_cumulative_incidence_at(
        high_investment_eia["duration_days"].to_numpy(float),
        high_investment_eia["competing_event"].to_numpy(int),
        event_of_interest=1,
        horizon_days=24 * DAYS_PER_MONTH,
    )
    bootstrap_note = (
        "EIA de inversión >=100 MMUS$; intervalo percentil de 2.000 réplicas "
        "por familia de reingreso, con semilla fija 20261002."
    )
    for suffix, label, value, recalculated in (
        ("estimacion", "Estimación central", central, central_independent),
        (
            "ic95_inf",
            "Límite inferior IC 95% bootstrap",
            primary_interval[0],
            independent_interval[0],
        ),
        (
            "ic95_sup",
            "Límite superior IC 95% bootstrap",
            primary_interval[1],
            independent_interval[1],
        ),
    ):
        rows.append(
            _claim(
                f"eia_100m_aj_aprobado_24m_{suffix}",
                f"{label}: aprobación AJ de EIA >=100 MMUS$ a 24 meses",
                float(value),
                "%",
                str(sea_path.relative_to(PROJECT_ROOT)),
                "Bootstrap percentil sobre la incidencia acumulada Aalen–Johansen.",
                float(recalculated),
                0.05,
                bootstrap_note,
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
                "EIA de la cartera en evaluación al corte SEA",
                eia_n,
                "proyectos",
                str(portfolio_path.relative_to(PROJECT_ROOT)),
                "Conteo de EIA confirmadas con evento en_tramite.",
                int(eia_sql["n"]),
                0.0,
                "El corte analítico corresponde a la vigencia de datos 25-08-2026.",
            ),
            _claim(
                "eia_en_evaluacion_inversion",
                "Inversión de EIA de la cartera en evaluación al corte SEA",
                eia_amount,
                "MMUS$",
                str(portfolio_path.relative_to(PROJECT_ROOT)),
                "Suma de inversión de EIA confirmadas con evento en_tramite.",
                float(eia_sql["inversion_musd"]),
                0.1,
                "El corte analítico corresponde a la vigencia de datos 25-08-2026.",
            ),
        ]
    )
    modification_ids = _checklist_modification_ids(checklist)
    approved_ids = set(
        portfolio.loc[portfolio["estado_ambiental"].eq("aprobado"), "project_id"].astype(str)
    )
    pending_modification_ids = set(
        pd.to_numeric(
            sea.loc[sea["evento"].eq("en_tramite"), "exp_id"], errors="raise"
        ).astype(int)
    )
    approved_with_pending_update = set(
        modification_ids.loc[
            modification_ids["project_id"].isin(approved_ids)
            & modification_ids["modification_exp_id"].isin(pending_modification_ids),
            "project_id",
        ]
    )
    independent_update_n, independently_counted_amount = (
        _independent_pending_update_summary(
            checklist_path,
            portfolio_path,
            sea_path,
        )
    )
    update_amount = float(
        portfolio.loc[
            portfolio["project_id"].astype(str).isin(approved_with_pending_update),
            "inversion_musd",
        ].sum()
    )
    rows.extend(
        [
            _claim(
                "aprobado_con_actualizacion_en_calificacion_n",
                "Proyectos con RCA favorable y actualización en calificación",
                len(approved_with_pending_update),
                "proyectos",
                str(checklist_path.relative_to(PROJECT_ROOT)),
                "Proyectos aprobados con una modificación curada cuya ficha SEA "
                "está en calificación.",
                independent_update_n,
                0,
                "La RCA principal sigue vigente; la actualización de la misma familia "
                "está en calificación.",
            ),
            _claim(
                "aprobado_con_actualizacion_en_calificacion_inversion",
                "Inversión con RCA favorable y actualización en calificación",
                update_amount,
                "MMUS$",
                str(checklist_path.relative_to(PROJECT_ROOT)),
                "Suma de inversión de proyectos aprobados con modificación curada en calificación.",
                independently_counted_amount,
                0.1,
                "La RCA principal sigue vigente; la actualización de la misma familia "
                "está en calificación.",
            ),
        ]
    )
    excluded_floor_ids = {
        "compania-minera-dona-ines-de-collahuasi-scm-proyecto-4a-linea-nueva-conentradora-en-rosario",
    }
    study_mask = portfolio["estado_ambiental"].eq("sin_expediente_en_estudio")
    floor_amount = float(
        portfolio.loc[study_mask & ~portfolio["project_id"].isin(excluded_floor_ids),
                      "inversion_musd"].sum()
    )
    ceiling_states = {
        "sin_expediente_en_estudio",
        "agregado_no_asignable",
        "no_determinado",
    }
    ceiling_amount = float(
        portfolio.loc[portfolio["estado_ambiental"].isin(ceiling_states),
                      "inversion_musd"].sum()
    )
    reviewed_n = int(portfolio["criterio"].eq("decision_J_checklist").sum())
    automatic_n = int(
        portfolio["criterio"].isin({"regla_auto", "regla_reingreso"}).sum()
    )
    period_start = int(population["fecha_ingreso"].dt.year.min())
    period_end = int(population["fecha_ingreso"].dt.year.max())
    rows.extend(
        [
            _claim(
                "poblacion_periodo_inicio",
                "Año inicial de ingreso de la población",
                period_start,
                "año",
                str(sea_path.relative_to(PROJECT_ROOT)),
                "Año mínimo de fecha_ingreso en la población principal.",
                int(population["fecha_ingreso"].min().year),
                0,
                "Periodo observado de expedientes admitidos.",
            ),
            _claim(
                "poblacion_periodo_fin",
                "Año final de ingreso de la población",
                period_end,
                "año",
                str(sea_path.relative_to(PROJECT_ROOT)),
                "Año máximo de fecha_ingreso en la población principal.",
                int(population["fecha_ingreso"].max().year),
                0,
                "Periodo observado de expedientes admitidos.",
            ),
            _claim(
                "cruces_revision_manual_n",
                "Cruces revisados ficha por ficha",
                reviewed_n,
                "proyectos",
                str(portfolio_path.relative_to(PROJECT_ROOT)),
                "Conteo con criterio decision_J_checklist.",
                int(portfolio["criterio"].astype(str).str.fullmatch("decision_J_checklist").sum()),
                0,
                "No incluye los cruces automáticos pendientes de confirmación.",
            ),
            _claim(
                "cruces_regla_auto_n",
                "Cruces automáticos pendientes de revisión",
                automatic_n,
                "proyectos",
                str(portfolio_path.relative_to(PROJECT_ROOT)),
                "Conteo de regla_auto y regla_reingreso.",
                int(portfolio["criterio"].isin(["regla_auto", "regla_reingreso"]).sum()),
                0,
                "Estas filas mantienen bloqueada la publicación hasta respuesta de J.",
            ),
            _claim(
                "headline_piso_pct",
                "Piso de sensibilidad del titular",
                100 * floor_amount / total,
                "%",
                str(portfolio_path.relative_to(PROJECT_ROOT)),
                "Sin expediente en estudio, excluyendo una clasificación disputable.",
                100 * floor_amount / total_sql,
                0.05,
                "Excluye el project_id documentado por la auditoría.",
            ),
            _claim(
                "headline_techo_pct",
                "Techo de sensibilidad del titular",
                100 * ceiling_amount / total,
                "%",
                str(portfolio_path.relative_to(PROJECT_ROOT)),
                "Suma sin expediente en estudio, agregado no asignable y no determinado.",
                100 * ceiling_amount / total_sql,
                0.05,
                "Cota superior de clasificación, no estimación puntual.",
            ),
            _claim(
                "sea_fecha_datos_dia",
                "Día del último registro SEA",
                25,
                "día",
                str(sea_path.relative_to(PROJECT_ROOT)),
                "Día de la fecha máxima entre ingreso, cierre y RCA.",
                int(
                    pd.concat(
                        [pd.to_datetime(sea[column], errors="coerce") for column in
                         ("fecha_ingreso", "fecha_cierre", "exp_fecha_rca")]
                    ).max().day
                ),
                0,
                "Fecha de vigencia del extracto, distinta de la descarga.",
            ),
            _claim(
                "sea_fecha_datos_mes",
                "Mes del último registro SEA",
                8,
                "mes",
                str(sea_path.relative_to(PROJECT_ROOT)),
                "Mes de la fecha máxima entre ingreso, cierre y RCA.",
                int(
                    pd.concat(
                        [pd.to_datetime(sea[column], errors="coerce") for column in
                         ("fecha_ingreso", "fecha_cierre", "exp_fecha_rca")]
                    ).max().month
                ),
                0,
                "Fecha de vigencia del extracto, distinta de la descarga.",
            ),
            _claim(
                "sea_fecha_datos_anio",
                "Año del último registro SEA",
                2026,
                "año",
                str(sea_path.relative_to(PROJECT_ROOT)),
                "Año de la fecha máxima entre ingreso, cierre y RCA.",
                int(
                    pd.concat(
                        [pd.to_datetime(sea[column], errors="coerce") for column in
                         ("fecha_ingreso", "fecha_cierre", "exp_fecha_rca")]
                    ).max().year
                ),
                0,
                "Fecha de vigencia del extracto, distinta de la descarga.",
            ),
            _claim(
                "headline_amount_round_mmusd",
                "Inversión sin expediente en estudio redondeada a centenas",
                round(float(portfolio.loc[study_mask, "inversion_musd"].sum()), -2),
                "MMUS$",
                str(portfolio_path.relative_to(PROJECT_ROOT)),
                "Redondeo a centenas del monto sin expediente en estudio.",
                round(
                    float(
                        environmental_sql.loc[
                            "sin_expediente_en_estudio", "inversion_musd"
                        ]
                    ),
                    -2,
                ),
                0,
                "Se usa solo con signo aproximado en la implicancia principal.",
            ),
            _claim(
                "confidence_level_pct",
                "Nivel del intervalo bootstrap",
                95,
                "%",
                "src/cmip/validation.py",
                "Percentiles 0,025 y 0,975 del bootstrap.",
                100 * (0.975 - 0.025),
                0,
                "Nivel nominal del intervalo percentil.",
            ),
            _claim(
                "aj_threshold_pct",
                "Umbral de cruce AJ",
                50,
                "%",
                "src/cmip/validation.py",
                "Umbral usado para aj_EIA_mes_50pct.",
                100 * 0.5,
                0,
                "Solo se muestra si la curva lo alcanza.",
            ),
        ]
    )
    return finalize_claims_register(rows)


def build_sensitivity_table(
    population_path: Path = SURVIVAL_POPULATION_PATH,
    sea_path: Path = SEA_PATH,
) -> pd.DataFrame:
    """Calculate requested population-rule sensitivities outside the PDF."""
    population = pd.read_parquet(population_path).copy()
    population["duration_days"] = population["duration_days"].astype(float).clip(lower=0.5)
    with_i5 = _manual_population(
        pd.read_parquet(sea_path), include_excluded_tipologias=True
    )
    without_early_withdrawals = population.loc[
        ~(
            population["evento"].eq("desistido_o_abandonado")
            & population["duration_days"].le(60)
        )
    ].copy()
    deduplicated = population.copy()
    deduplicated["_family_id"] = _reentry_family_ids(deduplicated)
    deduplicated = (
        deduplicated.sort_values(["fecha_ingreso", "exp_id"])
        .drop_duplicates("_family_id", keep="last")
        .drop(columns="_family_id")
    )
    segments = {
        "Principal sin áridos": population,
        "Con áridos y no mineros i5*": with_i5,
        "Sin desistimientos <=60 días": without_early_withdrawals,
        "Reingresos deduplicados": deduplicated,
    }
    rows: list[dict[str, object]] = []
    for segment, segment_frame in segments.items():
        for instrument in ("DIA", "EIA"):
            group = segment_frame.loc[segment_frame["instrumento"].eq(instrument)]
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
    replicas: int = 2000,
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
    def estimate(frame: pd.DataFrame) -> float:
        curve = manual_aalen_johansen(
            frame["duration_days"], frame["competing_event"], event_of_interest=1
        )
        return 100 * _step_at(curve, "cumulative_incidence", 24 * DAYS_PER_MONTH)

    estimates = _cluster_bootstrap_cif(group, replicas, seed)
    lower, upper = np.quantile(estimates, [0.025, 0.975])
    return pd.DataFrame(
        [
            {
                "segmento": ">=100 MMUS$",
                "instrumento": "EIA",
                "n": len(group),
                "replicas": replicas,
                "semilla": seed,
                "bootstrap_unidad": "familia_reingreso",
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
    candidate_review: pd.DataFrame | None = None,
) -> pd.DataFrame:
    """Build J's obligations, retaining prior answers and archiving removed IDs."""
    portfolio = pd.read_parquet(portfolio_path)
    sea_source = pd.read_parquet(sea_path)
    sea = sea_source.set_index("exp_id")
    decisions = pd.read_csv(confirmed_match_path)
    decision_ids = decisions.loc[decisions["criterio"].eq("decision_J"), "cochilco_id"]
    portfolio_by_id = portfolio.set_index("project_id", drop=False)
    missing_decisions = set(decision_ids) - set(portfolio_by_id.index)
    if missing_decisions:
        raise ValueError(f"decision_J projects missing from portfolio: {sorted(missing_decisions)}")

    if candidate_review is None:
        cochilco_required = {
            "project_id",
            "nombre_del_proyecto",
            "empresa",
            "region",
        }
        sea_required = {
            "exp_id",
            "exp_nombre",
            "seco_nombre",
            "region",
            "estado",
            "fecha_ingreso",
        }
        if cochilco_required.issubset(portfolio) and sea_required.issubset(sea_source):
            from cmip.match import rank_candidates

            candidate_review = rank_candidates(portfolio, sea_source, top_n=1)
        else:
            candidate_review = pd.DataFrame()

    suggestions: dict[str, str] = {}
    if not candidate_review.empty:
        required_suggestion_columns = {
            "cochilco_id",
            "exp_id",
            "sea_nombre",
            "inversion_ratio",
        }
        missing_suggestion_columns = required_suggestion_columns.difference(
            candidate_review.columns
        )
        if missing_suggestion_columns:
            raise ValueError(
                "Missing candidate-review columns: "
                f"{sorted(missing_suggestion_columns)}"
            )
        for cochilco_id, candidates in candidate_review.groupby(
            "cochilco_id", sort=False, dropna=False
        ):
            candidate = candidates.iloc[0]
            if pd.isna(candidate["exp_id"]):
                continue
            ratio = candidate["inversion_ratio"]
            ratio_text = "NA" if pd.isna(ratio) else f"{float(ratio):.3f}"
            suggestions[str(cochilco_id)] = (
                f"{int(float(candidate['exp_id']))} | {candidate['sea_nombre']} | "
                f"inversion_ratio={ratio_text}"
            )

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
            "candidato_sugerido": suggestions.get(str(project["project_id"]), ""),
            "exp_id_confirmado": exp_id,
            "sea_nombre": sea_name,
            "url_expediente": expediente_url,
            "url_busqueda": f"https://www.google.com/search?q={encoded_query}",
            "pregunta": question,
            "respuesta_J": "",
            "fuente_J": "",
            "_group_order": group_order,
        }

    columns = [
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

    # The published 40-row review is immutable evidence. Extend it only with the
    # automatic assignments that had never been inspected project by project.
    has_automatic_decisions = "criterio" in decisions and decisions["criterio"].isin(
        {"regla_auto", "regla_reingreso"}
    ).any()
    if (
        checklist_path is not None
        and checklist_path.exists()
        and has_automatic_decisions
    ):
        from cmip.match import reentry_family_key

        existing = pd.read_csv(checklist_path, keep_default_na=False)
        automatic = decisions.loc[
            decisions["criterio"].isin({"regla_auto", "regla_reingreso"})
        ]
        additions: list[dict[str, object]] = []
        for decision in automatic.itertuples(index=False):
            cochilco_id = str(decision.cochilco_id)
            if cochilco_id not in portfolio_by_id.index:
                raise ValueError(f"Automatic project missing from portfolio: {cochilco_id}")
            project = portfolio_by_id.loc[cochilco_id].copy()
            principal = int(float(decision.exp_id_confirmado))
            project["exp_id_confirmado"] = principal
            row = checklist_row(
                project,
                "¿Confirmas el expediente principal asignado automáticamente?",
                group_order=3,
            )
            sea_case = sea.loc[principal]
            holder = sea_case.get("empresa_nombre")
            if pd.isna(holder) or not str(holder).strip():
                holder = sea_case.get("titular_nombre")
            family_key = reentry_family_key(sea_case["exp_nombre"], holder)
            family_ids: list[int] = []
            for candidate in sea_source.itertuples(index=False):
                candidate_holder = getattr(candidate, "empresa_nombre", "")
                if pd.isna(candidate_holder) or not str(candidate_holder).strip():
                    candidate_holder = getattr(candidate, "titular_nombre", "")
                if reentry_family_key(candidate.exp_nombre, candidate_holder) == family_key:
                    candidate_id = int(candidate.exp_id)
                    if candidate_id != principal:
                        family_ids.append(candidate_id)
            others = ",".join(str(value) for value in sorted(set(family_ids))) or "ninguno"
            row["candidato_sugerido"] = (
                f"{principal} | {sea_case['exp_nombre']} | otros_familia={others}"
            )
            additions.append(row)

        additions_frame = pd.DataFrame(additions).drop(columns="_group_order")
        existing_keys = set(
            zip(existing["cochilco_id"], existing["pregunta"], strict=True)
        )
        additions_frame = additions_frame.loc[
            ~additions_frame.apply(
                lambda row: (row["cochilco_id"], row["pregunta"]) in existing_keys,
                axis=1,
            )
        ]
        return pd.concat(
            [existing.loc[:, columns], additions_frame.loc[:, columns]],
            ignore_index=True,
        )

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

    # The original checklist already gave every execution-stage missing case an RCA
    # obligation. Add the other rule-based no-expediente cases without duplicating
    # those execution obligations; this is the set of 14 previously unseen projects.
    if "criterio" in portfolio:
        additional_missing = portfolio.loc[
            portfolio["exp_id_confirmado"].isna()
            & portfolio["criterio"].eq("regla_sin_expediente")
            & ~portfolio["etapa"].eq("Ejecución")
            & ~portfolio["project_id"].isin(set(decision_ids))
        ]
        for _, project in additional_missing.iterrows():
            rows.append(
                checklist_row(
                    project,
                    (
                        "¿Existe expediente propio 2011-2026 o el proyecto usa una RCA "
                        "previa o una consulta de pertinencia?"
                    ),
                    group_order=2,
                )
            )

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
    candidate_review: pd.DataFrame | None = None,
) -> pd.DataFrame:
    """Regenerate the checklist without discarding J responses or removed projects."""
    result = build_validation_checklist(
        portfolio_path,
        sea_path,
        confirmed_match_path,
        checklist_path=checklist_path,
        orphans_path=orphans_path,
        candidate_review=candidate_review,
    )
    _write_csv_atomically(result, checklist_path)
    return result


def main() -> None:
    """Print validation artifacts for review without overwriting J's checklist."""
    claims = build_claims_register()
    sensitivity = build_sensitivity_table()
    bootstrap = bootstrap_eia_high_investment_approval_24m()
    checklist = pd.read_csv(CHECKLIST_PATH, keep_default_na=False)
    answered = int(checklist["respuesta_J"].astype(str).str.strip().ne("").sum())
    print("\nRegistro de cifras\n", claims.to_string(index=False))
    print("\nSensibilidad\n", sensitivity.to_string(index=False))
    print("\nBootstrap\n", bootstrap.to_string(index=False))
    print(f"\nChecklist: {answered} / {len(checklist)} respondidas")


if __name__ == "__main__":
    main()
