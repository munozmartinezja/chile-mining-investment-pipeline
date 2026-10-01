"""Extract and transform SEA Tableau workbooks without retaining personal data."""

from __future__ import annotations

import re
import shutil
import tempfile
import unicodedata
from datetime import date
from pathlib import Path
from zipfile import ZipFile

import duckdb
import pandas as pd

from cmip.config import INTERIM_DIR, PROCESSED_DIR, PROJECT_ROOT

SEA_RAW_DIR = PROJECT_ROOT / "data" / "raw" / "sea"
SEA_DATABASE_PATH = PROCESSED_DIR / "cmip.duckdb"
CUTOFF_DATE = date(2026, 9, 30)
PRIVATE_COLUMNS = frozenset({"encargado_nombre", "encargado_rut", "titular_rut"})
PLAZOS_COLUMNS = (
    "exp_id",
    "eval_habil",
    "sus_habil",
    "sussea_habil",
    "dias_corridos",
    "exp_fecha_rca",
    "exp_nro_rca",
)
EVENTO_BY_ESTADO = {
    "Aprobado": "aprobado",
    "Caducado": "aprobado",
    "Revocado": "aprobado",
    "Renuncia RCA": "aprobado",
    "Rechazado": "rechazado",
    "Desistido": "desistido_o_abandonado",
    "Abandonado": "desistido_o_abandonado",
    "No Admitido a Tramitación": "no_admitido",
    "En Calificación": "en_tramite",
    "No calificado": "termino_anticipado",
}
POST_RCA_STATES = frozenset({"Caducado", "Revocado", "Renuncia RCA"})
TIMING_ANALYSIS_EVENTS = frozenset(
    {"aprobado", "rechazado", "en_tramite", "termino_anticipado"}
)
EXPECTED_MINING_STATES = {
    "Aprobado": 1043,
    "Desistido": 371,
    "No Admitido a Tramitación": 316,
    "No calificado": 122,
    "En Calificación": 58,
    "Rechazado": 36,
    "Caducado": 10,
}


def snake_case(value: object) -> str:
    """Normalize a Tableau column name to conservative ASCII snake_case."""
    text = unicodedata.normalize("NFKD", str(value))
    text = "".join(character for character in text if not unicodedata.combining(character))
    return re.sub(r"[^a-z0-9]+", "_", text.casefold()).strip("_")


def _drop_private_columns(frame: pd.DataFrame) -> pd.DataFrame:
    frame = frame.drop(columns=list(PRIVATE_COLUMNS.intersection(frame.columns)))
    if PRIVATE_COLUMNS.intersection(frame.columns):
        raise AssertionError("SEA privacy columns survived extraction")
    return frame


def _hyper_select_expression(column: object) -> str:
    """Return a Hyper SELECT expression that materializes dates as ISO text."""
    from tableauhyperapi import TypeTag

    name = str(column.name)
    if column.type.tag in {TypeTag.DATE, TypeTag.TIMESTAMP, TypeTag.TIMESTAMP_TZ}:
        return f"CAST({name} AS TEXT) AS {name}"
    return name


def _read_hyper(path: Path) -> pd.DataFrame | None:
    try:
        from tableauhyperapi import Connection, HyperProcess, TableName, Telemetry
    except ModuleNotFoundError as error:  # pragma: no cover - depends on optional runtime install
        raise RuntimeError(
            "tableauhyperapi is required to read SEA TWBX extracts; install project dependencies"
        ) from error

    table_name = TableName("Extract", "Extract")
    with (
        HyperProcess(Telemetry.DO_NOT_SEND_USAGE_DATA_TO_TABLEAU) as process,
        Connection(process.endpoint, str(path)) as connection,
    ):
        if not connection.catalog.has_table(table_name):
            return None
        definition = connection.catalog.get_table_definition(table_name)
        safe_columns = [
            column
            for column in definition.columns
            if snake_case(column.name.unescaped) not in PRIVATE_COLUMNS
        ]
        projection = ", ".join(_hyper_select_expression(column) for column in safe_columns)
        rows = connection.execute_list_query(f"SELECT {projection} FROM {table_name}")

    frame = pd.DataFrame(
        rows, columns=[snake_case(column.name.unescaped) for column in safe_columns]
    )
    return _drop_private_columns(frame)


def read_twbx(path: Path) -> pd.DataFrame:
    """Read the logical Extract.Extract table from a packaged Tableau workbook."""
    with ZipFile(path) as archive:
        candidates = [
            name
            for name in archive.namelist()
            if name.casefold().endswith((".tmp", ".hyper"))
            and Path(name).name.casefold() != "v3.hyper"
        ]
        if not candidates:
            raise ValueError(f"No non-geometry Hyper extract found in {path.name}")

        for member in candidates:
            with tempfile.NamedTemporaryFile(suffix=".hyper") as temporary:
                with archive.open(member) as source:
                    shutil.copyfileobj(source, temporary)
                temporary.flush()
                frame = _read_hyper(Path(temporary.name))
                if frame is not None:
                    return frame
    raise ValueError(f'No Hyper file with table "Extract"."Extract" found in {path.name}')


def _normalize_input(frame: pd.DataFrame) -> pd.DataFrame:
    normalized = frame.copy()
    normalized.columns = [snake_case(column) for column in normalized.columns]
    return _drop_private_columns(normalized)


def _parse_datetime_column(frame: pd.DataFrame, column: str) -> None:
    try:
        frame[column] = pd.to_datetime(frame[column], errors="raise", format="mixed")
    except (TypeError, ValueError) as error:
        raise ValueError(f"Invalid date value in {column}: {error}") from error


def _prepare_plazos(plazos: pd.DataFrame) -> pd.DataFrame:
    normalized = _normalize_input(plazos)
    if normalized.empty and "exp_id" not in normalized:
        return pd.DataFrame(columns=PLAZOS_COLUMNS)
    missing = set(PLAZOS_COLUMNS).difference(normalized.columns)
    if missing:
        raise ValueError(f"SEA plazos extract missing columns: {sorted(missing)}")
    selected = normalized.loc[:, PLAZOS_COLUMNS].copy()
    duplicates = selected.loc[selected["exp_id"].duplicated(), "exp_id"].tolist()
    if duplicates:
        raise ValueError(f"Duplicate exp_id values in SEA plazos: {duplicates[:10]}")
    _parse_datetime_column(selected, "exp_fecha_rca")
    return selected


def build_sea_frames(
    ingresados: pd.DataFrame,
    plazos: pd.DataFrame,
    cutoff: date = CUTOFF_DATE,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Build all-sector and mining SEA tables with survival variables."""
    source = _normalize_input(ingresados)
    required = {
        "exp_id",
        "exp_nombre",
        "reg_romano",
        "work_alias",
        "texp_letra",
        "seco_nombre",
        "est_nombre",
        "mmu",
        "exp_fpres",
        "exp_fcierre",
        "titular_nombre",
        "empresa_nombre",
    }
    missing = required.difference(source.columns)
    if missing:
        raise ValueError(f"SEA ingresados extract missing columns: {sorted(missing)}")

    unmapped = sorted(set(source["est_nombre"].dropna()) - EVENTO_BY_ESTADO.keys())
    if source["est_nombre"].isna().any():
        unmapped.append("<NULL>")
    if unmapped:
        raise ValueError(f"Unmapped SEA states: {unmapped}")

    _parse_datetime_column(source, "exp_fpres")
    _parse_datetime_column(source, "exp_fcierre")
    if source["exp_fpres"].isna().any():
        raise ValueError("exp_fpres contains null values")

    projects = source.loc[:, sorted(required)].rename(
        columns={
            "work_alias": "instrumento",
            "est_nombre": "estado",
            "reg_romano": "region",
            "texp_letra": "tipologia",
            "mmu": "inversion_musd",
            "exp_fpres": "fecha_ingreso",
            "exp_fcierre": "fecha_cierre",
        }
    )
    projects = projects.merge(_prepare_plazos(plazos), on="exp_id", how="left", validate="1:1")

    duplicates = projects.loc[projects["exp_id"].duplicated(), "exp_id"].tolist()
    if duplicates:
        raise ValueError(f"Duplicate exp_id values in sea_projects: {duplicates[:10]}")
    projects["evento"] = projects["estado"].map(EVENTO_BY_ESTADO)
    projects["fecha_inconsistente"] = projects["fecha_cierre"].notna() & (
        projects["fecha_cierre"] < projects["fecha_ingreso"]
    )
    invalid_analysis_dates = projects["fecha_inconsistente"] & projects["evento"].isin(
        TIMING_ANALYSIS_EVENTS
    )
    if invalid_analysis_dates.any():
        invalid_ids = projects.loc[invalid_analysis_dates, "exp_id"].head(10).tolist()
        raise ValueError(
            "date inconsistencies in timing-analysis events; "
            f"sample exp_id values: {invalid_ids}"
        )

    effective_end = projects["fecha_cierre"].fillna(pd.Timestamp(cutoff))
    projects["duracion_dias"] = (effective_end - projects["fecha_ingreso"]).dt.days.astype(
        "Int64"
    )
    projects.loc[projects["fecha_inconsistente"], "duracion_dias"] = pd.NA
    if projects["duracion_dias"].dropna().lt(0).any():
        raise ValueError("duracion_dias must be non-negative")
    invalid_open = projects["fecha_cierre"].isna() & projects["evento"].ne("en_tramite")
    if invalid_open.any():
        invalid_ids = projects.loc[invalid_open, "exp_id"].head(10).tolist()
        raise ValueError(
            "fecha_cierre is null outside en_tramite; " f"sample exp_id values: {invalid_ids}"
        )
    missing_consistent_duration = projects["duracion_dias"].isna() & ~projects[
        "fecha_inconsistente"
    ]
    if missing_consistent_duration.any():
        raise ValueError("duracion_dias is null for a date-consistent record")
    projects["estado_post_rca"] = projects["estado"].where(
        projects["estado"].isin(POST_RCA_STATES), pd.NA
    )
    projects["admitido"] = projects["estado"].ne("No Admitido a Tramitación")
    projects = _drop_private_columns(projects)
    mining = projects.loc[projects["seco_nombre"].eq("Minería")].reset_index(drop=True)
    return projects.reset_index(drop=True), mining


def validate_mining_state_counts(mining: pd.DataFrame) -> None:
    """Enforce the verified 2026-09-30 mining-state regression counts."""
    counts = mining["estado"].value_counts().to_dict()
    mismatches = {
        state: (counts.get(state, 0), expected)
        for state, expected in EXPECTED_MINING_STATES.items()
        if counts.get(state, 0) != expected
    }
    remaining = sum(count for state, count in counts.items() if state not in EXPECTED_MINING_STATES)
    if mismatches or remaining != 5 or len(mining) != 1961:
        raise ValueError(
            "SEA mining state-count regression failed: "
            f"mismatches={mismatches}, remaining={remaining}, total={len(mining)}"
        )


def validate_date_inconsistency_count(projects: pd.DataFrame) -> None:
    """Enforce the verified number of source-date anomalies at the cutoff."""
    actual = int(projects["fecha_inconsistente"].sum())
    if actual != 53:
        raise ValueError(f"Expected 53 date inconsistencies at cutoff; found {actual}")


def _load_frame(
    connection: duckdb.DuckDBPyConnection, table_name: str, frame: pd.DataFrame
) -> None:
    connection.register("_sea_frame", frame)
    connection.execute(f'CREATE OR REPLACE TABLE "{table_name}" AS SELECT * FROM _sea_frame')
    connection.unregister("_sea_frame")


def write_sea_outputs(
    projects: pd.DataFrame,
    mining: pd.DataFrame,
    interim_dir: Path = INTERIM_DIR,
    database_path: Path = SEA_DATABASE_PATH,
) -> tuple[Path, Path, Path]:
    """Write privacy-checked Parquet outputs and register both DuckDB tables."""
    for name, frame in (("sea_projects", projects), ("sea_mining", mining)):
        leaked = PRIVATE_COLUMNS.intersection(frame.columns)
        if leaked:
            raise ValueError(f"Refusing to write private SEA columns in {name}: {sorted(leaked)}")
    interim_dir.mkdir(parents=True, exist_ok=True)
    projects_path = interim_dir / "sea_projects.parquet"
    mining_path = interim_dir / "sea_mining.parquet"
    projects.to_parquet(projects_path, index=False)
    mining.to_parquet(mining_path, index=False)
    database_path.parent.mkdir(parents=True, exist_ok=True)
    with duckdb.connect(str(database_path)) as connection:
        _load_frame(connection, "sea_projects", projects)
        _load_frame(connection, "sea_mining", mining)
    return projects_path, mining_path, database_path


def build_sea_pipeline(
    raw_dir: Path = SEA_RAW_DIR,
    interim_dir: Path = INTERIM_DIR,
    database_path: Path = SEA_DATABASE_PATH,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Extract, validate, and persist the full SEA pipeline."""
    ingresados = read_twbx(raw_dir / "sea_proyectos_ingresados.twbx")
    plazos = read_twbx(raw_dir / "sea_plazos_tramitacion.twbx")
    projects, mining = build_sea_frames(ingresados, plazos)
    validate_date_inconsistency_count(projects)
    validate_mining_state_counts(mining)
    write_sea_outputs(projects, mining, interim_dir, database_path)
    return projects, mining


def main() -> None:
    projects, mining = build_sea_pipeline()
    print(f"SEA rows: ingresados={len(projects)}, mining={len(mining)}")


if __name__ == "__main__":
    main()
