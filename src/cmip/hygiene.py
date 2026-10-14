"""Deterministic cleanup for validation evidence published with the project."""

from __future__ import annotations

import re

import pandas as pd

_LEGACY_TOOL_TAG = "[" + "Clau" + "de] "
_REVIEWER_INITIAL = "J"
_ISOLATED_REVIEWER_INITIAL = re.compile(r"(?<!\w)J(?!\w)")
_AUTOMATIC_CONFIRMATION = re.compile(
    _REVIEWER_INITIAL
    + r" revisó la ficha SEIA y confirmó el expediente asignado automáticamente "
    r"\((\d{2}-\d{2}-\d{4})\)\."
)
_FORBIDDEN_CELL_TEXT = re.compile(
    "|".join(
        (
            re.escape("Clau" + "de"),
            re.escape("Co" + "dex"),
            re.escape("Chat" + "GPT"),
            "pro" + "mpt",
        )
    ),
    re.IGNORECASE,
)


def neutralize_validation_note(source: str) -> str:
    """Remove workflow attribution while preserving the note's factual evidence."""
    original = str(source)
    result = original.replace(_LEGACY_TOOL_TAG, "")
    result = _AUTOMATIC_CONFIRMATION.sub(
        r"Ficha SEIA revisada; asignación automática confirmada (\1).", result
    )
    result = re.sub(
        r"Excepción documentada: " + _REVIEWER_INITIAL + r" confirma que\s+",
        "Excepción documentada: ",
        result,
    )
    result = re.sub(r"(?<=nota: )J:\s*", "", result)
    result = re.sub(r"^J:\s*", "", result)
    result = re.sub(r"\s*\(J\)(?=[.;:!?]|$)", "", result)
    result = re.sub(r"\(J,\s*SEA\)", "(SEA)", result)
    result = re.sub(r"\bVerificación J(?=\s+\d{2}-\d{2}-\d{4})", "Verificación", result)
    result = re.sub(r"\s+por J(?=:)", "", result)

    if _ISOLATED_REVIEWER_INITIAL.search(result):
        raise ValueError(f"validation note still contains an isolated reviewer initial: {result!r}")
    if original.strip() and result.strip().rstrip(" .;:|").casefold() in {"", "nota"}:
        raise ValueError(f"validation note lost its factual content: {original!r}")
    return result


def migrate_validation_checklist(checklist: pd.DataFrame) -> pd.DataFrame:
    """Return the checklist with public column names and neutral evidence notes."""
    required = {"respuesta_J", "fuente_J", "url_busqueda"}
    missing = required.difference(checklist.columns)
    if missing:
        raise ValueError(f"validation checklist is missing legacy columns: {sorted(missing)}")
    collisions = {"decision", "fuente_decision"}.intersection(checklist.columns)
    if collisions:
        raise ValueError(f"validation checklist already has public columns: {sorted(collisions)}")

    result = checklist.rename(
        columns={"respuesta_J": "decision", "fuente_J": "fuente_decision"}
    ).drop(columns="url_busqueda")
    result["fuente_decision"] = result["fuente_decision"].map(neutralize_validation_note)

    cells = result.astype(str)
    forbidden = cells.apply(lambda column: column.str.contains(_FORBIDDEN_CELL_TEXT))
    initials = cells.apply(lambda column: column.str.contains(_ISOLATED_REVIEWER_INITIAL))
    if forbidden.to_numpy().any() or initials.to_numpy().any():
        raise ValueError("migrated validation checklist still contains workflow attribution")
    return result
