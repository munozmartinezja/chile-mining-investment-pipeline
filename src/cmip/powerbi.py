"""Export the compact, privacy-safe Power BI data model."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

from cmip.config import PROCESSED_DIR, PROJECT_ROOT
from cmip.survival import DAYS_PER_MONTH
from cmip.validation import build_claims_register

POWERBI_DIR = PROJECT_ROOT / "data" / "powerbi"
PORTFOLIO_PATH = PROCESSED_DIR / "cochilco_seia.parquet"
POPULATION_PATH = PROCESSED_DIR / "survival_population.parquet"
KM_PATH = PROCESSED_DIR / "survival_km.parquet"
CIF_PATH = PROCESSED_DIR / "survival_competing_risks.parquet"
TREND_PATH = PROCESSED_DIR / "survival_trend.parquet"
MONTHS = range(73)

POWERBI_SCHEMAS = {
    "fact_cartera": pa.schema(
        [
            pa.field("project_id", pa.string()),
            pa.field("nombre_proyecto", pa.string()),
            pa.field("empresa", pa.string()),
            pa.field("mina", pa.string()),
            pa.field("region", pa.string()),
            pa.field("macro_zona", pa.string()),
            pa.field("etapa", pa.string()),
            pa.field("condicion", pa.string()),
            pa.field("tipo", pa.string()),
            pa.field("pem_inicio", pa.int16()),
            pa.field("pem_fin", pa.int16()),
            pa.field("inversion_musd", pa.float64()),
            pa.field("estado_ambiental", pa.string()),
            pa.field("estado_ambiental_label_es", pa.string()),
            pa.field("estado_ambiental_orden", pa.int8()),
            pa.field("exp_id_confirmado", pa.int64()),
            pa.field("instrumento", pa.string()),
            pa.field("fecha_ingreso", pa.date32()),
            pa.field("estado_sea", pa.string()),
            pa.field("criterio", pa.string()),
        ]
    ),
    "fact_expedientes": pa.schema(
        [
            pa.field("exp_id", pa.int64()),
            pa.field("instrumento", pa.string()),
            pa.field("region", pa.string()),
            pa.field("macro_zona", pa.string()),
            pa.field("tipologia", pa.string()),
            pa.field("inversion_musd", pa.float64()),
            pa.field("segmento_inversion", pa.string()),
            pa.field("fecha_ingreso", pa.date32()),
            pa.field("fecha_cierre", pa.date32()),
            pa.field("anio_ingreso", pa.int16()),
            pa.field("evento", pa.string()),
            pa.field("duracion_dias", pa.int32()),
            pa.field("duracion_meses", pa.float64()),
            pa.field("en_cartera_cochilco", pa.bool_()),
        ]
    ),
    "agg_km": pa.schema(
        [
            pa.field("instrumento", pa.string()),
            pa.field("mes", pa.int16()),
            pa.field("prob_aprobado", pa.float64()),
            pa.field("ic_inf", pa.float64()),
            pa.field("ic_sup", pa.float64()),
        ]
    ),
    "agg_cif": pa.schema(
        [
            pa.field("instrumento", pa.string()),
            pa.field("desenlace", pa.string()),
            pa.field("mes", pa.int16()),
            pa.field("incidencia", pa.float64()),
        ]
    ),
    "agg_tendencia": pa.schema(
        [
            pa.field("anio_ingreso", pa.int16()),
            pa.field("instrumento", pa.string()),
            pa.field("mediana_meses", pa.float64()),
            pa.field("n", pa.int32()),
            pa.field("cohorte_incompleta", pa.bool_()),
        ]
    ),
    "kpi_validados": pa.schema(
        [
            pa.field("claim_id", pa.string()),
            pa.field("texto_es", pa.string()),
            pa.field("texto_en", pa.string()),
            pa.field("valor", pa.float64()),
            pa.field("unidad", pa.string()),
            pa.field("estado", pa.string()),
        ]
    ),
}

ENVIRONMENTAL_STATUS = {
    "aprobado": ("Aprobado", 1),
    "en_evaluacion": ("En evaluación", 2),
    "desistido_o_rechazado": ("Desistido o rechazado", 3),
    "pertinencia": ("Pertinencia", 4),
    "rca_previa_2011": ("RCA previa a 2011", 5),
    "agregado_no_asignable": ("Agregado no asignable", 6),
    "sin_expediente_en_ejecucion": ("Sin expediente: en ejecución", 7),
    "sin_expediente_en_estudio": ("Sin expediente: en estudio", 8),
    "no_determinado": ("No determinado", 9),
    "otro": ("Otro", 10),
}

STATE_LABELS_EN = {
    "aprobado": "approved",
    "en_evaluacion": "under review",
    "desistido_o_rechazado": "withdrawn or rejected",
    "otro": "other",
    "agregado_no_asignable": "non-assignable aggregate",
    "rca_previa_2011": "pre-2011 RCA",
    "pertinencia": "applicability ruling",
    "no_determinado": "undetermined",
    "sin_expediente_en_ejecucion": "without a filing, in execution",
    "sin_expediente_en_estudio": "without a filing, in study",
}

OUTCOME_LABELS_EN = {
    "aprobado": "approved",
    "desistido_o_abandonado": "withdrawn or abandoned",
    "rechazado": "rejected",
    "termino_anticipado": "early termination",
}


def macro_zone(region: object) -> str:
    """Return the three-zone grouping used by the Cox model."""
    normalized = str(region).strip().casefold()
    if normalized in {
        "xv",
        "i",
        "ii",
        "arica y parinacota",
        "tarapacá",
        "tarapaca",
        "antofagasta",
    }:
        return "Norte Grande"
    if normalized in {"iii", "iv", "atacama", "coquimbo"}:
        return "Norte Chico"
    return "Centro-Sur"


def _frame_to_table(name: str, frame: pd.DataFrame) -> pa.Table:
    schema = POWERBI_SCHEMAS[name]
    selected = frame.loc[:, schema.names]
    empty_columns = [column for column in selected if selected[column].isna().all()]
    if empty_columns:
        raise ValueError(f"{name} contains all-null columns: {empty_columns}")
    table = pa.Table.from_pandas(selected, schema=schema, preserve_index=False, safe=True)
    null_types = [field.name for field in table.schema if pa.types.is_null(field.type)]
    if null_types:
        raise TypeError(f"{name} contains Arrow null columns: {null_types}")
    return table


def _portfolio_table(portfolio: pd.DataFrame) -> pa.Table:
    statuses = portfolio["estado_ambiental"].map(ENVIRONMENTAL_STATUS)
    if statuses.isna().any():
        unknown = sorted(portfolio.loc[statuses.isna(), "estado_ambiental"].unique())
        raise ValueError(f"Unknown environmental status values: {unknown}")
    frame = pd.DataFrame(
        {
            "project_id": portfolio["project_id"],
            "nombre_proyecto": portfolio["nombre_del_proyecto"],
            "empresa": portfolio["empresa"],
            "mina": portfolio["mina"],
            "region": portfolio["region"],
            "macro_zona": portfolio["region"].map(macro_zone),
            "etapa": portfolio["etapa"],
            "condicion": portfolio["condicion"],
            "tipo": portfolio["tipo"],
            "pem_inicio": portfolio["pem_inicio"].astype("int16"),
            "pem_fin": portfolio["pem_fin"].astype("int16"),
            "inversion_musd": portfolio["inversion_musd"].astype(float),
            "estado_ambiental": portfolio["estado_ambiental"],
            "estado_ambiental_label_es": statuses.map(lambda value: value[0]),
            "estado_ambiental_orden": statuses.map(lambda value: value[1]).astype("int8"),
            "exp_id_confirmado": pd.to_numeric(
                portfolio["exp_id_confirmado"], errors="coerce"
            ).astype("Int64"),
            "instrumento": portfolio["instrumento"],
            "fecha_ingreso": pd.to_datetime(portfolio["fecha_ingreso"]).dt.date,
            "estado_sea": portfolio["estado"],
            "criterio": portfolio["criterio"],
        }
    )
    return _frame_to_table("fact_cartera", frame)


def _population_table(population: pd.DataFrame, portfolio: pd.DataFrame) -> pa.Table:
    duration = population["duration_days"].astype(float)
    if not np.equal(duration, np.floor(duration)).all():
        raise ValueError("fact_expedientes duration_days must contain whole days")
    confirmed_ids = set(
        pd.to_numeric(portfolio["exp_id_confirmado"], errors="coerce")
        .dropna()
        .astype("int64")
    )
    entry_dates = pd.to_datetime(population["fecha_ingreso"])
    frame = pd.DataFrame(
        {
            "exp_id": population["exp_id"].astype("int64"),
            "instrumento": population["instrumento"],
            "region": population["region"],
            "macro_zona": population["region"].map(macro_zone),
            "tipologia": population["tipologia"],
            "inversion_musd": population["inversion_musd"].astype(float),
            "segmento_inversion": np.where(
                population["inversion_musd"].ge(100), "≥100 MMUS$", "<100 MMUS$"
            ),
            "fecha_ingreso": entry_dates.dt.date,
            "fecha_cierre": pd.to_datetime(population["fecha_cierre"]).dt.date,
            "anio_ingreso": entry_dates.dt.year.astype("int16"),
            "evento": population["evento"],
            "duracion_dias": duration.astype("int32"),
            "duracion_meses": duration / DAYS_PER_MONTH,
            "en_cartera_cochilco": population["exp_id"].isin(confirmed_ids),
        }
    )
    return _frame_to_table("fact_expedientes", frame)


def _monthly_step_rows(
    source: pd.DataFrame,
    group_columns: list[str],
    value_columns: list[str],
) -> list[dict[str, object]]:
    records: list[dict[str, object]] = []
    grouper: str | list[str] = group_columns[0] if len(group_columns) == 1 else group_columns
    for group_key, group in source.groupby(grouper, sort=True, observed=True):
        keys = (group_key,) if len(group_columns) == 1 else group_key
        ordered = group.sort_values("time_days")
        times = ordered["time_days"].to_numpy(dtype=float)
        if len(times) == 0 or times[0] > 0:
            raise ValueError(f"Curve {keys} has no value at or before month zero")
        values = {
            column: ordered[column].to_numpy(dtype=float) for column in value_columns
        }
        for month in MONTHS:
            index = int(np.searchsorted(times, month * DAYS_PER_MONTH, side="right") - 1)
            record = dict(zip(group_columns, keys, strict=True))
            record["mes"] = month
            record.update({column: array[index] for column, array in values.items()})
            records.append(record)
    return records


def _km_table(km: pd.DataFrame) -> pa.Table:
    values = ["approval_probability", "approval_ci_lower", "approval_ci_upper"]
    frame = pd.DataFrame(_monthly_step_rows(km, ["instrumento"], values)).rename(
        columns={
            "approval_probability": "prob_aprobado",
            "approval_ci_lower": "ic_inf",
            "approval_ci_upper": "ic_sup",
        }
    )
    return _frame_to_table("agg_km", frame)


def _cif_table(cif: pd.DataFrame) -> pa.Table:
    frame = pd.DataFrame(
        _monthly_step_rows(cif, ["instrumento", "outcome"], ["cumulative_incidence"])
    ).rename(columns={"outcome": "desenlace", "cumulative_incidence": "incidencia"})
    return _frame_to_table("agg_cif", frame)


def _trend_table(trend: pd.DataFrame) -> pa.Table:
    frame = pd.DataFrame(
        {
            "anio_ingreso": trend["anio_ingreso"].astype("int16"),
            "instrumento": trend["instrumento"],
            "mediana_meses": trend["mediana_dias_aprobados"].astype(float)
            / DAYS_PER_MONTH,
            "n": trend["n_aprobados"].astype("int32"),
            "cohorte_incompleta": trend["cohorte_incompleta"].astype(bool),
        }
    )
    return _frame_to_table("agg_tendencia", frame)


def _english_claim_text(claim_id: str) -> str:
    exact = {
        "cartera_inversion_total": "Total portfolio investment",
        "cartera_proyectos_n": "Projects in the Cochilco portfolio",
        "sea_poblacion_admitida_n": "Admitted mining filings in the survival population",
        "clasificacion_ingenua_sin_permiso_pct": (
            "Share that a naive classification marked as lacking a permit"
        ),
        "eia_100m_aj_aprobado_24m_estimacion": (
            "Central estimate: 24-month AJ approval for EIAs ≥US$100m"
        ),
        "eia_100m_aj_aprobado_24m_ic95_inf": (
            "Lower bootstrap 95% CI: 24-month AJ approval for EIAs ≥US$100m"
        ),
        "eia_100m_aj_aprobado_24m_ic95_sup": (
            "Upper bootstrap 95% CI: 24-month AJ approval for EIAs ≥US$100m"
        ),
        "eia_en_evaluacion_n": "Portfolio EIAs currently under review",
        "eia_en_evaluacion_inversion": "Investment in portfolio EIAs currently under review",
    }
    if claim_id in exact:
        return exact[claim_id]
    if claim_id.startswith("estado_"):
        suffix = claim_id.removeprefix("estado_")
        metric = next(
            (candidate for candidate in ("_inversion", "_pct", "_n") if suffix.endswith(candidate)),
            None,
        )
        if metric is not None:
            state = suffix.removesuffix(metric)
            label = STATE_LABELS_EN.get(state)
            if label is not None:
                prefix = {
                    "_inversion": "Investment in environmental status",
                    "_pct": "Share of investment in environmental status",
                    "_n": "Projects in environmental status",
                }[metric]
                return f"{prefix}: {label}"
    if claim_id.startswith("km_"):
        _, instrument, metric = claim_id.split("_", 2)
        labels = {
            "mediana": "KM median",
            "ic95_inf": "Lower 95% CI for the KM median",
            "ic95_sup": "Upper 95% CI for the KM median",
            "aprobado_24m": "24-month KM approval probability",
        }
        if metric in labels:
            return f"{labels[metric]}: {instrument}"
    if claim_id.startswith("aj_") and claim_id.endswith("_24m"):
        _, instrument, outcome = claim_id.removesuffix("_24m").split("_", 2)
        label = OUTCOME_LABELS_EN.get(outcome)
        if label is not None:
            return f"24-month cumulative incidence: {label}, {instrument}"
    raise ValueError(f"Missing English KPI text for claim_id={claim_id!r}")


def _kpi_table(claims: pd.DataFrame) -> pa.Table:
    verified = claims.loc[claims["estado"].eq("verificada")].copy()
    frame = pd.DataFrame(
        {
            "claim_id": verified["claim_id"],
            "texto_es": verified["texto_es"],
            "texto_en": verified["claim_id"].map(_english_claim_text),
            "valor": verified["valor"].astype(float),
            "unidad": verified["unidad"],
            "estado": verified["estado"],
        }
    ).reset_index(drop=True)
    return _frame_to_table("kpi_validados", frame)


def build_powerbi_tables(
    portfolio_path: Path = PORTFOLIO_PATH,
    population_path: Path = POPULATION_PATH,
    km_path: Path = KM_PATH,
    cif_path: Path = CIF_PATH,
    trend_path: Path = TREND_PATH,
    claims: pd.DataFrame | None = None,
) -> dict[str, pa.Table]:
    """Build all six Power BI tables against explicit Arrow schemas."""
    paths = (portfolio_path, population_path, km_path, cif_path, trend_path)
    missing = [str(path) for path in paths if not path.exists()]
    if missing:
        raise FileNotFoundError(f"Required Power BI sources are missing: {missing}")
    portfolio = pd.read_parquet(portfolio_path)
    return {
        "fact_cartera": _portfolio_table(portfolio),
        "fact_expedientes": _population_table(pd.read_parquet(population_path), portfolio),
        "agg_km": _km_table(pd.read_parquet(km_path)),
        "agg_cif": _cif_table(pd.read_parquet(cif_path)),
        "agg_tendencia": _trend_table(pd.read_parquet(trend_path)),
        "kpi_validados": _kpi_table(build_claims_register() if claims is None else claims),
    }


def write_powerbi_exports(
    output_dir: Path = POWERBI_DIR,
    **build_kwargs: object,
) -> dict[str, pa.Table]:
    """Write all Power BI Parquet files and return the in-memory tables."""
    tables = build_powerbi_tables(**build_kwargs)
    output_dir.mkdir(parents=True, exist_ok=True)
    for name, table in tables.items():
        pq.write_table(table, output_dir / f"{name}.parquet", compression="snappy")
    return tables


def main() -> None:
    """Generate the Power BI export directory."""
    tables = write_powerbi_exports()
    for name, table in tables.items():
        print(f"Wrote {name}.parquet ({table.num_rows} rows)")


if __name__ == "__main__":
    main()
