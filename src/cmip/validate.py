"""Validation and normalization for the Cochilco project catalog."""

from __future__ import annotations

import math
import re
import unicodedata
from enum import StrEnum
from typing import Literal

import pandas as pd
from pydantic import BaseModel, ConfigDict, field_validator


class TipoProyecto(StrEnum):
    """Closed project-type vocabulary observed in Annex C Table 1."""

    EXPANSION = "Expansión"
    NUEVO = "Nuevo"
    REPOSICION = "Reposición"


class CochilcoProject(BaseModel):
    """Normalized schema for a Table 1 project row."""

    model_config = ConfigDict(extra="forbid")

    project_id: str
    puesta_en_marcha: str
    pem_inicio: int
    pem_fin: int
    empresa: str
    mina: str
    nombre_del_proyecto: str
    sector: str
    region: str
    tipo: TipoProyecto
    etapa: Literal["Ingeniería Conceptual", "Prefactibilidad", "Factibilidad", "Ejecución"]
    condicion: Literal["Base", "Probable", "Posible", "Potencial"]
    inversion_musd: float
    nota_agregacion: bool

    @field_validator("inversion_musd")
    @classmethod
    def amount_is_finite_and_nonnegative(cls, value: float) -> float:
        if not math.isfinite(value) or value < 0:
            raise ValueError("inversion_musd must be finite and nonnegative")
        return value

    @field_validator("empresa", "nombre_del_proyecto", "sector", "region")
    @classmethod
    def required_text_is_not_blank(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("required text fields cannot be blank")
        return value


AGGREGATION_PROJECTS = (
    "Chuquicamata Subterránea",
    "Nuevo Nivel Mina",
    "Súlfuros RT Fase II",
    "Otros Proyectos de Desarrollo",
    "Tranques",
)


def parse_chilean_number(value: object) -> float:
    """Parse dot-thousands/comma-decimal numbers used in Chilean reports."""
    if isinstance(value, int | float) and not isinstance(value, bool):
        if pd.isna(value):
            raise ValueError("amount cannot be null")
        return float(value)
    text = str(value).strip()
    if not text:
        raise ValueError("amount cannot be blank")
    return float(text.replace(".", "").replace(",", "."))


def _year_text(value: object) -> str:
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value).strip()


def _required_source_text(value: object, field_name: str) -> str:
    if value is None or pd.isna(value):
        raise ValueError(f"{field_name} cannot be null")
    text = str(value).strip()
    if not text:
        raise ValueError(f"{field_name} cannot be blank")
    return text


def parse_puesta_en_marcha(value: object) -> tuple[int, int]:
    """Parse a single year or inclusive year range without losing source text."""
    text = _year_text(value)
    match = re.fullmatch(r"(\d{4})(?:\s*[-–]\s*(\d{4}))?", text)
    if not match:
        raise ValueError(f"Unsupported puesta en marcha value: {text!r}")
    start = int(match.group(1))
    end = int(match.group(2) or start)
    if end < start:
        raise ValueError("puesta en marcha range ends before it starts")
    return start, end


def project_slug(empresa: object, nombre_del_proyecto: object) -> str:
    """Build a stable ASCII slug from company and project name."""
    source = f"{empresa} {nombre_del_proyecto}".lower().strip()
    source = "".join(
        character
        for character in unicodedata.normalize("NFKD", source)
        if not unicodedata.combining(character)
    )
    return re.sub(r"[^a-z0-9]+", "-", source).strip("-")


def normalize_projects(raw: pd.DataFrame) -> pd.DataFrame:
    """Validate and normalize every project in extracted Table 1."""
    required = {
        "Puesta en Marcha",
        "Empresa",
        "Mina",
        "Nombre del Proyecto",
        "Sector",
        "Región",
        "Tipo de Proyecto",
        "Etapa de Avance",
        "Condición",
        "Inversión [MMUS$]",
    }
    missing = required.difference(raw.columns)
    if missing:
        raise ValueError(f"Table 1 missing columns: {sorted(missing)}")

    projects: list[dict[str, object]] = []
    for row in raw.to_dict("records"):
        puesta = _year_text(row["Puesta en Marcha"])
        pem_inicio, pem_fin = parse_puesta_en_marcha(puesta)
        empresa = _required_source_text(row["Empresa"], "empresa")
        project_name = _required_source_text(row["Nombre del Proyecto"], "nombre_del_proyecto")
        model = CochilcoProject(
            project_id=project_slug(empresa, project_name),
            puesta_en_marcha=puesta,
            pem_inicio=pem_inicio,
            pem_fin=pem_fin,
            empresa=empresa,
            mina=str(row["Mina"]).strip(),
            nombre_del_proyecto=project_name,
            sector=_required_source_text(row["Sector"], "sector"),
            region=_required_source_text(row["Región"], "region"),
            tipo=str(row["Tipo de Proyecto"]).strip(),
            etapa=str(row["Etapa de Avance"]).strip(),
            condicion=str(row["Condición"]).strip(),
            inversion_musd=round(parse_chilean_number(row["Inversión [MMUS$]"]), 1),
            nota_agregacion=any(name in project_name for name in AGGREGATION_PROJECTS),
        )
        projects.append(model.model_dump(mode="json"))

    result = pd.DataFrame(projects)
    duplicates = result.loc[result["project_id"].duplicated(), "project_id"].tolist()
    if duplicates:
        raise ValueError(f"Duplicate project_id values: {duplicates}")
    return result


def mineral_from_sector(sector: str) -> str:
    """Map the detailed Table 1 sector to the mineral groups in control tables."""
    if "Cu" in sector or sector == "Plantas Metalurgicas":
        return "Cobre"
    if sector == "Min. Industrial":
        return "Otros"
    return sector


def _control_number(value: object) -> float:
    return round(parse_chilean_number(value), 1)


def reconcile_condition_mineral(
    projects: pd.DataFrame, control: pd.DataFrame
) -> pd.DataFrame:
    """Compare Table 1 with Table 4 by condition and mineral, without adjustment."""
    detail = projects.assign(mineral=projects["sector"].map(mineral_from_sector))
    actual = detail.groupby(["condicion", "mineral"], as_index=False)["inversion_musd"].sum()
    actual_lookup = {
        (row.condicion, row.mineral): row.inversion_musd for row in actual.itertuples()
    }

    rows: list[dict[str, object]] = []
    minerals = ["Cobre", "Oro", "Litio", "Hierro", "Otros"]
    condition_column = control.columns[0]
    for record in control.to_dict("records"):
        condition = str(record[condition_column]).strip()
        if str(record["Unidad"]).strip() != "MMUS$" or condition not in {
            "Base",
            "Probable",
            "Posible",
            "Potencial",
        }:
            continue
        for mineral in minerals:
            table_1 = float(actual_lookup.get((condition, mineral), 0.0))
            table_4 = _control_number(record[mineral])
            rows.append(
                {
                    "condicion": condition,
                    "mineral": mineral,
                    "table_1_musd": table_1,
                    "table_4_musd": table_4,
                    "difference_musd": round(table_1 - table_4, 1),
                }
            )
    return pd.DataFrame(rows)


def reconcile_project_count(projects: pd.DataFrame, control: pd.DataFrame) -> dict[str, int]:
    """Compare physical catalog rows with Table 4's expanded project count."""
    label_column = control.columns[0]
    match = control.loc[control[label_column].astype(str).str.strip() == "N° de proyectos"]
    if len(match) != 1:
        raise ValueError("Table 4 project-count row not found uniquely")
    control_projects = int(_control_number(match.iloc[0]["Total"]))
    table_1_rows = len(projects)
    return {
        "table_1_rows": table_1_rows,
        "control_projects": control_projects,
        "difference": table_1_rows - control_projects,
    }


def reconcile_regions(projects: pd.DataFrame, control: pd.DataFrame) -> pd.DataFrame:
    """Compare Table 1 region totals with Table 8's investment rows."""
    actual = projects.groupby("region")["inversion_musd"].sum().to_dict()
    label_column = control.columns[0]
    rows: list[dict[str, object]] = []
    for record in control.to_dict("records"):
        region = str(record[label_column]).strip()
        if str(record["Unidad"]).strip() != "MMUS$" or region == "Inversión":
            continue
        table_1 = float(actual.get(region, 0.0))
        table_8 = _control_number(record["Total"])
        rows.append(
            {
                "region": region,
                "table_1_musd": table_1,
                "table_8_musd": table_8,
                "difference_musd": round(table_1 - table_8, 1),
            }
        )
    return pd.DataFrame(rows)


def reconcile_temporal_total(
    projects: pd.DataFrame, control: pd.DataFrame
) -> dict[str, float]:
    """Compare Table 1's total with the rounded period buckets in Table 10."""
    label_column = control.columns[0]
    match = control.loc[control[label_column].astype(str).str.strip() == "Total Inversión"]
    if len(match) != 1:
        raise ValueError("Table 10 total row not found uniquely")
    period_columns = [
        column for column in control.columns if column not in {label_column, "Unidad"}
    ]
    table_10 = round(sum(_control_number(match.iloc[0][column]) for column in period_columns), 1)
    table_1 = round(float(projects["inversion_musd"].sum()), 1)
    return {
        "table_1_musd": table_1,
        "table_10_musd": table_10,
        "difference_musd": round(table_1 - table_10, 1),
    }
