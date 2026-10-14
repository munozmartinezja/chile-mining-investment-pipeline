"""Reconcile the pipeline SEA extract against the official transparency response."""

from __future__ import annotations

import hashlib
import json
import warnings
from collections.abc import Mapping
from pathlib import Path
from tempfile import TemporaryDirectory

import pandas as pd

from cmip.config import (
    PROCESSED_DIR,
    PROJECT_ROOT,
    SEA_OFFICIAL_PATH,
    SEA_OFFICIAL_RESPONSE_DATE,
    SEA_OFFICIAL_SUMMARY_PATH,
)
from cmip.extract.sea import EVENTO_BY_ESTADO, POST_RCA_STATES
from cmip.survival import main_population_exclusion_reasons

RECONCILIATION_COLUMNS = [
    "exp_id",
    "campo",
    "valor_nuestro",
    "valor_oficial",
    "posterior_al_corte",
    "en_poblacion_995",
]
COMPARISONS = (
    ("instrumento", "instrumento"),
    ("tipologia", "tipologia"),
    ("estado", "estado"),
    ("fecha_ingreso", "fecha_ingreso"),
    ("fecha_cierre", "fecha_cierre"),
    ("inversion_musd", "inversion_musd"),
)
CATEGORY_ORDER = (
    "presencia_oficial",
    "presencia_nuestra",
    "instrumento",
    "tipologia",
    "estado",
    "fecha_ingreso",
    "fecha_cierre",
    "inversion_musd",
)
DEFAULT_CSV_PATH = PROJECT_ROOT / "docs/reconciliation_sea_oficial.csv"
DEFAULT_MARKDOWN_PATH = PROJECT_ROOT / "docs/reconciliation_sea_oficial.md"
SUMMARY_KEYS = (
    "expedientes_coinciden_n",
    "diferencias_previas_al_corte_n",
    "fecha_respuesta",
    "corte",
    "filas_oficiales",
    "sha256_archivo_oficial",
)


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def build_reconciliation_summary(
    nuestra: pd.DataFrame,
    oficial: pd.DataFrame,
    *,
    official_path: Path,
    corte: str | pd.Timestamp = "2026-08-25",
) -> dict[str, object]:
    """Build the publishable integrity summary for the private official CSV."""
    cutoff = pd.Timestamp(corte).date().isoformat()
    differences = reconcile_sea(nuestra, oficial, corte=cutoff)
    return {
        "expedientes_coinciden_n": len(set(nuestra["exp_id"]) & set(oficial["exp_id"])),
        "diferencias_previas_al_corte_n": int(
            (~differences["posterior_al_corte"]).sum()
        ),
        "fecha_respuesta": SEA_OFFICIAL_RESPONSE_DATE.isoformat(),
        "corte": cutoff,
        "filas_oficiales": len(oficial),
        "sha256_archivo_oficial": _sha256_file(official_path),
    }


def load_reconciliation_summary(path: Path = SEA_OFFICIAL_SUMMARY_PATH) -> dict[str, object]:
    """Load and validate the versioned, privacy-safe reconciliation summary."""
    if not path.exists():
        raise FileNotFoundError(f"Falta el resumen versionado de conciliación SEA: {path}")
    try:
        summary = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError) as error:
        raise ValueError(f"Resumen SEA oficial inválido en {path}: {error}") from error
    if not isinstance(summary, dict) or set(summary) != set(SUMMARY_KEYS):
        actual = sorted(summary) if isinstance(summary, dict) else type(summary).__name__
        raise ValueError(
            "Resumen SEA oficial inválido: "
            f"se esperaban campos {list(SUMMARY_KEYS)}; recibidos={actual}"
        )
    for field in (
        "expedientes_coinciden_n",
        "diferencias_previas_al_corte_n",
        "filas_oficiales",
    ):
        if not isinstance(summary[field], int) or isinstance(summary[field], bool):
            raise ValueError(f"Resumen SEA oficial inválido: {field} debe ser entero")
    for field in ("fecha_respuesta", "corte"):
        try:
            parsed = pd.Timestamp(summary[field])
        except (TypeError, ValueError) as error:
            raise ValueError(
                f"Resumen SEA oficial inválido: {field} no es una fecha ISO"
            ) from error
        if parsed.date().isoformat() != summary[field]:
            raise ValueError(f"Resumen SEA oficial inválido: {field} debe usar YYYY-MM-DD")
    digest = summary["sha256_archivo_oficial"]
    if not isinstance(digest, str) or len(digest) != 64 or any(
        character not in "0123456789abcdef" for character in digest
    ):
        raise ValueError("Resumen SEA oficial inválido: sha256_archivo_oficial no es SHA-256")
    return summary


def write_reconciliation_summary(
    summary: Mapping[str, object], path: Path = SEA_OFFICIAL_SUMMARY_PATH
) -> Path:
    """Write the privacy-safe summary using a stable, reviewable JSON layout."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(dict(summary), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return path


def resolve_reconciliation_summary(
    nuestra: pd.DataFrame,
    *,
    official_path: Path = SEA_OFFICIAL_PATH,
    summary_path: Path = SEA_OFFICIAL_SUMMARY_PATH,
) -> dict[str, object]:
    """Use the versioned summary and verify it against the private CSV when present."""
    stored = load_reconciliation_summary(summary_path)
    if not official_path.exists():
        return stored
    from cmip.sea_oficial import load_sea_oficial

    calculated = build_reconciliation_summary(
        nuestra,
        load_sea_oficial(official_path),
        official_path=official_path,
        corte=str(stored["corte"]),
    )
    mismatches = [field for field in SUMMARY_KEYS if stored[field] != calculated[field]]
    if mismatches:
        raise ValueError(
            "El resumen SEA oficial no coincide con el CSV privado; "
            f"campos distintos: {mismatches}. Regenere la conciliación explícitamente."
        )
    return stored


def _population_ids(nuestra: pd.DataFrame) -> set[int]:
    if "en_poblacion_995" in nuestra:
        mask = nuestra["en_poblacion_995"].fillna(False).astype(bool)
    else:
        required = {"admitido", "fecha_inconsistente", "tipologia", "exp_nombre"}
        missing = required - set(nuestra.columns)
        if missing:
            raise ValueError(
                f"No se puede identificar la población 995; faltan columnas: {sorted(missing)}"
            )
        mask = (
            nuestra["admitido"].eq(True)
            & nuestra["fecha_inconsistente"].eq(False)
            & main_population_exclusion_reasons(nuestra).eq("")
        )
    return set(nuestra.loc[mask, "exp_id"].astype(int))


def _display_value(value: object) -> object:
    if value is None or pd.isna(value):
        return ""
    if isinstance(value, pd.Timestamp):
        return value.date().isoformat()
    if isinstance(value, float):
        return f"{value:.9g}"
    return value


def _different(ours: object, official: object, field: str) -> bool:
    if pd.isna(ours) and pd.isna(official):
        return False
    if pd.isna(ours) != pd.isna(official):
        return True
    if field == "inversion_musd":
        return abs(float(ours) - float(official)) > 0.5
    return bool(ours != official)


def _posterior(row: pd.Series, field: str, cutoff: pd.Timestamp) -> bool:
    if field in {"estado", "fecha_cierre"}:
        return bool(pd.notna(row["fecha_cierre_oficial"]) and row["fecha_cierre_oficial"] > cutoff)
    if field == "presencia_nuestra":
        return bool(row["fecha_ingreso_oficial"] > cutoff)
    if field == "presencia_oficial":
        return bool(row["fecha_ingreso_nuestra"] > cutoff)
    return bool(
        pd.notna(row.get("fecha_ingreso_oficial")) and row["fecha_ingreso_oficial"] > cutoff
    )


def reconcile_sea(
    nuestra: pd.DataFrame,
    oficial: pd.DataFrame,
    corte: str | pd.Timestamp = "2026-08-25",
) -> pd.DataFrame:
    """Return one privacy-safe row for every presence or field difference."""
    cutoff = pd.Timestamp(corte)
    if nuestra["exp_id"].duplicated().any() or oficial["exp_id"].duplicated().any():
        raise ValueError("exp_id debe ser único en ambas bases para conciliar")
    population_ids = _population_ids(nuestra)
    ours = nuestra.set_index("exp_id")
    official = oficial.set_index("exp_id")
    rows: list[dict[str, object]] = []

    for exp_id in sorted(set(ours.index) - set(official.index)):
        context = pd.Series(
            {
                "fecha_ingreso_nuestra": ours.loc[exp_id, "fecha_ingreso"],
                "fecha_ingreso_oficial": pd.NaT,
            }
        )
        rows.append(
            {
                "exp_id": int(exp_id),
                "campo": "presencia_oficial",
                "valor_nuestro": True,
                "valor_oficial": False,
                "posterior_al_corte": _posterior(context, "presencia_oficial", cutoff),
                "en_poblacion_995": int(exp_id) in population_ids,
            }
        )
    for exp_id in sorted(set(official.index) - set(ours.index)):
        context = pd.Series(
            {
                "fecha_ingreso_nuestra": pd.NaT,
                "fecha_ingreso_oficial": official.loc[exp_id, "fecha_ingreso"],
            }
        )
        rows.append(
            {
                "exp_id": int(exp_id),
                "campo": "presencia_nuestra",
                "valor_nuestro": False,
                "valor_oficial": True,
                "posterior_al_corte": _posterior(context, "presencia_nuestra", cutoff),
                "en_poblacion_995": False,
            }
        )

    for exp_id in sorted(set(ours.index) & set(official.index)):
        context = pd.Series(
            {
                "fecha_ingreso_nuestra": ours.loc[exp_id, "fecha_ingreso"],
                "fecha_ingreso_oficial": official.loc[exp_id, "fecha_ingreso"],
                "fecha_cierre_oficial": official.loc[exp_id, "fecha_cierre"],
            }
        )
        for field, official_field in COMPARISONS:
            our_value = ours.loc[exp_id, field]
            official_value = official.loc[exp_id, official_field]
            if not _different(our_value, official_value, field):
                continue
            rows.append(
                {
                    "exp_id": int(exp_id),
                    "campo": field,
                    "valor_nuestro": _display_value(our_value),
                    "valor_oficial": _display_value(official_value),
                    "posterior_al_corte": _posterior(context, field, cutoff),
                    "en_poblacion_995": int(exp_id) in population_ids,
                }
            )
    result = pd.DataFrame(rows, columns=RECONCILIATION_COLUMNS)
    if not result.empty:
        result["posterior_al_corte"] = result["posterior_al_corte"].astype(bool)
        result["en_poblacion_995"] = result["en_poblacion_995"].astype(bool)
        order = {category: index for index, category in enumerate(CATEGORY_ORDER)}
        result["_order"] = result["campo"].map(order)
        result = result.sort_values(["_order", "exp_id"]).drop(columns="_order")
    return result.reset_index(drop=True)


def apply_official_at_cutoff(
    nuestra: pd.DataFrame,
    oficial: pd.DataFrame,
    corte: str | pd.Timestamp = "2026-08-25",
) -> pd.DataFrame:
    """Replace SEA fields with official values while censoring later outcomes."""
    cutoff = pd.Timestamp(corte)
    result = nuestra.copy().set_index("exp_id")
    source = oficial.set_index("exp_id")
    common = result.index.intersection(source.index)
    for column in ("instrumento", "tipologia", "fecha_ingreso", "inversion_musd"):
        result.loc[common, column] = source.loc[common, column].to_numpy()

    official_close = source.loc[common, "fecha_cierre"]
    later_close = official_close.gt(cutoff)
    result.loc[common, "fecha_cierre"] = official_close.where(~later_close, pd.NaT).to_numpy()
    official_state = source.loc[common, "estado"].where(~later_close, "En Calificación")
    result.loc[common, "estado"] = official_state.to_numpy()

    result = result.reset_index()
    result["evento"] = result["estado"].map(EVENTO_BY_ESTADO)
    unmapped = result.loc[result["evento"].isna(), "estado"].drop_duplicates().tolist()
    if unmapped:
        raise ValueError(f"Estados SEA oficiales sin mapeo: {unmapped}")
    result["fecha_inconsistente"] = result["fecha_cierre"].notna() & (
        result["fecha_cierre"] < result["fecha_ingreso"]
    )
    effective_end = result["fecha_cierre"].fillna(cutoff)
    result["duracion_dias"] = (effective_end - result["fecha_ingreso"]).dt.days.astype("Int64")
    result.loc[result["fecha_inconsistente"], "duracion_dias"] = pd.NA
    result["admitido"] = result["estado"].ne("No Admitido a Tramitación")
    if "estado_post_rca" in result:
        result["estado_post_rca"] = result["estado"].where(
            result["estado"].isin(POST_RCA_STATES), pd.NA
        )
    return result


def write_reconciliation_outputs(
    differences: pd.DataFrame,
    *,
    csv_path: Path = DEFAULT_CSV_PATH,
    markdown_path: Path = DEFAULT_MARKDOWN_PATH,
    claim_impact: pd.DataFrame | None = None,
) -> tuple[Path, Path]:
    """Write privacy-safe reconciliation details and category/claim summaries."""
    safe = differences.loc[:, RECONCILIATION_COLUMNS].copy()
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    safe.to_csv(csv_path, index=False)
    counts = safe["campo"].value_counts()
    lines = [
        "# Conciliación con base oficial SEA (Ley 20.285)",
        "",
        "Corte analítico: **25-08-2026**. Los eventos posteriores se tratan como censura.",
        "",
        "## Diferencias por categoría",
        "",
        "| Categoría | Filas | Previas o al corte | Posteriores al corte |",
        "| --- | ---: | ---: | ---: |",
    ]
    for category in CATEGORY_ORDER:
        group = safe.loc[safe["campo"].eq(category)]
        lines.append(
            f"| {category} | {int(counts.get(category, 0))} | "
            f"{int((~group['posterior_al_corte']).sum())} | "
            f"{int(group['posterior_al_corte'].sum())} |"
        )
    if claim_impact is not None:
        lines.extend(
            [
                "",
                "## Impacto en el registro de cifras",
                "",
                "| claim_id | Antes | Después | Unidad | Cambia al redondeo publicado |",
                "| --- | ---: | ---: | --- | --- |",
            ]
        )
        for row in claim_impact.itertuples(index=False):
            lines.append(
                f"| {row.claim_id} | {row.antes} | {row.despues} | {row.unidad} | "
                f"{str(bool(row.cambia_al_redondeo)).lower()} |"
            )
    markdown_path.parent.mkdir(parents=True, exist_ok=True)
    markdown_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return csv_path, markdown_path


def _portfolio_with_official_status(
    portfolio: pd.DataFrame, reconciled_sea: pd.DataFrame
) -> pd.DataFrame:
    from cmip.portfolio_status import SEA_STATUS_COLUMNS, classify_environmental_status

    status_columns = [column for column in SEA_STATUS_COLUMNS if column != "exp_id"]
    base = portfolio.drop(columns=[column for column in status_columns if column in portfolio])
    result = base.merge(
        reconciled_sea.loc[:, SEA_STATUS_COLUMNS],
        how="left",
        left_on="exp_id_confirmado",
        right_on="exp_id",
        validate="many_to_one",
    )
    missing = result["exp_id_confirmado"].notna() & result["exp_id"].isna()
    if missing.any():
        ids = result.loc[missing, "exp_id_confirmado"].astype(int).tolist()
        raise ValueError(f"Expedientes confirmados ausentes tras conciliación: {ids}")
    overrides = result.get("estado_ambiental_override", pd.Series("", index=result.index)).fillna(
        ""
    )
    result["estado_ambiental"] = [
        str(override).strip() or classify_environmental_status(evento, exp_id, etapa)
        for evento, exp_id, etapa, override in zip(
            result["evento"],
            result["exp_id_confirmado"],
            result.get("etapa", pd.Series(pd.NA, index=result.index)),
            overrides,
            strict=True,
        )
    ]
    return result.drop(columns="exp_id")


def _rounded_claim(value: object, unit: str) -> object:
    if value is None or pd.isna(value):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return str(value)
    if unit in {"proyectos", "expedientes", "diferencias", "año", "día", "mes"}:
        return int(round(number))
    return round(number, 1)


def build_claim_impact(
    nuestra: pd.DataFrame,
    oficial: pd.DataFrame,
    corte: str | pd.Timestamp = "2026-08-25",
) -> pd.DataFrame:
    """Recalculate the complete claims register with official SEA fields."""
    from cmip.portfolio_status import PORTFOLIO_STATUS_PATH
    from cmip.survival import (
        build_survival_population,
        extract_competing_risk_tables,
        extract_km_tables,
        fit_competing_risks,
        fit_kaplan_meier,
    )
    from cmip.validation import (
        AJ_SUMMARY_PATH,
        CHECKLIST_PATH,
        KM_SUMMARY_PATH,
        build_claims_register,
    )

    reconciled = apply_official_at_cutoff(nuestra, oficial, corte=corte)
    population = build_survival_population(reconciled)
    _, km_summary = extract_km_tables(fit_kaplan_meier(population))
    with warnings.catch_warnings():
        warnings.filterwarnings("ignore", message="Tied event times.*")
        _, aj_summary = extract_competing_risk_tables(fit_competing_risks(population))
    portfolio = _portfolio_with_official_status(pd.read_parquet(PORTFOLIO_STATUS_PATH), reconciled)

    with TemporaryDirectory(prefix="sea-oficial-", dir=PROCESSED_DIR) as temporary:
        temp = Path(temporary)
        sea_path = temp / "sea_mining.parquet"
        portfolio_path = temp / "cochilco_seia.parquet"
        km_path = temp / KM_SUMMARY_PATH.name
        aj_path = temp / AJ_SUMMARY_PATH.name
        reconciled.to_parquet(sea_path, index=False)
        portfolio.to_parquet(portfolio_path, index=False)
        km_summary.to_parquet(km_path, index=False)
        aj_summary.to_parquet(aj_path, index=False)
        before = build_claims_register(official_path=SEA_OFFICIAL_PATH)
        after = build_claims_register(
            portfolio_path=portfolio_path,
            sea_path=sea_path,
            km_summary_path=km_path,
            aj_summary_path=aj_path,
            checklist_path=CHECKLIST_PATH,
            official_path=temp / "official-not-present.csv",
        )

    before = before.set_index("claim_id")
    after = after.set_index("claim_id")
    if set(before.index) != set(after.index):
        raise ValueError("El registro antes y después no contiene los mismos claim_id")
    claims_map = pd.read_csv(PROJECT_ROOT / "docs/brief/claims_map.csv", keep_default_na=False)
    published_ids = {
        claim_id
        for value in claims_map.loc[claims_map["lang"].isin(["es", "en"]), "claim_ids"]
        for claim_id in value.split(";")
        if claim_id
    }
    records = []
    for claim_id in before.index:
        unit = str(before.loc[claim_id, "unidad"])
        before_value = before.loc[claim_id, "valor"]
        after_value = after.loc[claim_id, "valor"]
        changed = claim_id in published_ids and (
            _rounded_claim(before_value, unit) != _rounded_claim(after_value, unit)
        )
        records.append(
            {
                "claim_id": claim_id,
                "antes": before_value,
                "despues": after_value,
                "unidad": unit,
                "cambia_al_redondeo": changed,
            }
        )
    return pd.DataFrame(records)


def main() -> None:
    """Generate the official reconciliation and stop on a published rounded change."""
    from cmip.sea_oficial import load_sea_oficial
    from cmip.validation import SEA_PATH

    nuestra = pd.read_parquet(SEA_PATH)
    oficial = load_sea_oficial(SEA_OFFICIAL_PATH)
    differences = reconcile_sea(nuestra, oficial)
    summary = build_reconciliation_summary(
        nuestra,
        oficial,
        official_path=SEA_OFFICIAL_PATH,
        corte="2026-08-25",
    )
    write_reconciliation_summary(summary)
    impact = build_claim_impact(nuestra, oficial)
    write_reconciliation_outputs(differences, claim_impact=impact)
    changed = impact.loc[impact["cambia_al_redondeo"]]
    if not changed.empty:
        raise RuntimeError(
            "La conciliación cambia cifras publicadas al redondeo del brief: "
            f"{changed['claim_id'].tolist()}. No se regeneró el brief."
        )
    print(
        f"Conciliación SEA oficial: {len(differences)} diferencias; "
        "0 cifras publicadas cambian al redondeo"
    )


if __name__ == "__main__":
    main()
