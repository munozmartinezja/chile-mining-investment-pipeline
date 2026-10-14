"""Load the official SEA transparency response without writing private data."""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from cmip.extract.sea import snake_case

EXPECTED_COLUMNS = frozenset(
    {
        "id_expediente",
        "nombre_proyecto",
        "tipo_de_presentacion",
        "region",
        "comuna",
        "provincia",
        "tipologia",
        "sector_productivo",
        "razon_de_ingreso",
        "estado",
        "monto_inversion",
        "titular",
        "empresa",
        "fecha_presentacion",
        "fecha_cierre",
        "dias_corridos",
        "dias_evaluacion_inhabil",
        "dias_evaluacion_habil",
        "dias_suspension_inhabil",
        "dias_suspension_habil",
        "coordenada_x",
        "coordenada_y",
        "link_expediente",
    }
)
DAY_COLUMNS = (
    "dias_corridos",
    "dias_evaluacion_inhabil",
    "dias_evaluacion_habil",
    "dias_suspension_inhabil",
    "dias_suspension_habil",
)


def _parse_decimal_comma(series: pd.Series, column: str) -> pd.Series:
    try:
        return pd.to_numeric(series.str.replace(",", ".", regex=False), errors="raise").astype(
            "Float64"
        )
    except (TypeError, ValueError) as error:
        raise ValueError(f"Valor numérico inválido en {column}: {error}") from error


def load_sea_oficial(path: str | Path) -> pd.DataFrame:
    """Read and normalize the 23-column official SEA transparency CSV."""
    source = Path(path)
    raw = source.read_bytes()
    if not raw.startswith(b"\xef\xbb\xbf"):
        raise ValueError("Formato SEA oficial inválido: se esperaba UTF-8 con BOM")
    first_line = raw.splitlines()[0] if raw else b""
    if b";" not in first_line:
        raise ValueError("Formato SEA oficial inválido: se esperaba separador ';' y 23 columnas")

    try:
        frame = pd.read_csv(
            source,
            sep=";",
            encoding="utf-8-sig",
            dtype=str,
            keep_default_na=False,
        )
    except pd.errors.ParserError as error:
        raise ValueError(
            f"No se pudo leer el CSV SEA oficial con separador ';': {error}"
        ) from error
    frame.columns = [snake_case(column) for column in frame.columns]
    actual = set(frame.columns)
    missing = sorted(EXPECTED_COLUMNS - actual)
    extra = sorted(actual - EXPECTED_COLUMNS)
    if missing or extra or len(frame.columns) != 23:
        raise ValueError(
            "esquema SEA oficial inválido: se esperaban 23 columnas; "
            f"faltantes={missing}, adicionales={extra}"
        )

    presentation = frame.pop("tipo_de_presentacion").str.strip()
    frame["instrumento"] = presentation.str.split().str[0]
    frame["reglamento"] = presentation.str.extract(r"\b(DS(?:17|40))\b", expand=False).fillna("")
    frame = frame.rename(
        columns={
            "id_expediente": "exp_id",
            "fecha_presentacion": "fecha_ingreso",
            "monto_inversion": "inversion_musd",
        }
    )

    try:
        frame["exp_id"] = pd.to_numeric(frame["exp_id"], errors="raise").astype("int64")
    except (TypeError, ValueError) as error:
        raise ValueError(f"ID_EXPEDIENTE inválido: {error}") from error
    if frame["exp_id"].duplicated().any():
        duplicate = int(frame.loc[frame["exp_id"].duplicated(), "exp_id"].iloc[0])
        raise ValueError(f"ID_EXPEDIENTE duplicado en base SEA oficial: {duplicate}")

    for column in ("fecha_ingreso", "fecha_cierre"):
        values = frame[column].replace("", pd.NA)
        try:
            frame[column] = pd.to_datetime(values, format="%d/%m/%Y", errors="raise")
        except (TypeError, ValueError) as error:
            raise ValueError(f"Fecha inválida en {column}: {error}") from error

    amount = frame["inversion_musd"].replace("", "0").str.replace(".", "", regex=False)
    try:
        frame["inversion_musd"] = pd.to_numeric(amount, errors="raise") / 1_000_000
    except (TypeError, ValueError) as error:
        raise ValueError(f"MONTO_INVERSION inválido: {error}") from error
    for column in DAY_COLUMNS:
        try:
            frame[column] = pd.to_numeric(frame[column].replace("", pd.NA), errors="raise").astype(
                "Int64"
            )
        except (TypeError, ValueError) as error:
            raise ValueError(f"Día inválido en {column}: {error}") from error
    for column in ("coordenada_x", "coordenada_y"):
        frame[column] = _parse_decimal_comma(frame[column].replace("", pd.NA), column)
    return frame
