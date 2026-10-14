from __future__ import annotations

import re

import pandas as pd
import pytest

from cmip.hygiene import migrate_validation_checklist, neutralize_validation_note

_TOOL_NAME = "Clau" + "de"


@pytest.mark.parametrize(
    ("source", "expected"),
    [
        (
            f"nota: [{_TOOL_NAME}] J revisó la ficha SEIA y confirmó el expediente "
            "asignado automáticamente (09-10-2026).",
            "nota: Ficha SEIA revisada; asignación automática confirmada (09-10-2026).",
        ),
        (
            f"nota: [{_TOOL_NAME}] Excepción documentada: J confirma que es el mismo "
            "proyecto.",
            "nota: Excepción documentada: es el mismo proyecto.",
        ),
        (
            f"nota: [{_TOOL_NAME}] Excepción documentada: mismo proyecto (J); comparte "
            "expediente.",
            "nota: Excepción documentada: mismo proyecto; comparte expediente.",
        ),
        (
            f"nota: [{_TOOL_NAME}] J: Fase I = concentradora.",
            "nota: Fase I = concentradora.",
        ),
        (
            f"nota: [{_TOOL_NAME}] RCA encontradas por J: 20269900127.",
            "nota: RCA encontradas: 20269900127.",
        ),
        (
            f"nota: [{_TOOL_NAME}] Verificación J 09-10-2026: búsqueda sin EIA.",
            "nota: Verificación 09-10-2026: búsqueda sin EIA.",
        ),
        (
            f"nota: [{_TOOL_NAME}] Revisados (J, SEA): 2158456424.",
            "nota: Revisados (SEA): 2158456424.",
        ),
    ],
)
def test_neutralize_validation_note_removes_workflow_attribution(
    source: str, expected: str
) -> None:
    result = neutralize_validation_note(source)

    assert result == expected
    assert not re.search(r"(?<!\w)J(?!\w)", result)


def test_neutralize_validation_note_rejects_unhandled_attribution() -> None:
    with pytest.raises(ValueError, match="isolated reviewer initial"):
        neutralize_validation_note("nota: confirmado personalmente por J.")


def test_migrate_validation_checklist_renames_columns_and_drops_search_url() -> None:
    original = pd.DataFrame(
        {
            "cochilco_id": ["project-a"],
            "url_busqueda": ["https://example.test/search"],
            "respuesta_J": ["confirmado"],
            "fuente_J": [f"nota: [{_TOOL_NAME}] J: evidencia conservada."],
        }
    )

    migrated = migrate_validation_checklist(original)

    assert migrated.columns.tolist() == [
        "cochilco_id",
        "decision",
        "fuente_decision",
    ]
    assert migrated.loc[0, "decision"] == "confirmado"
    assert migrated.loc[0, "fuente_decision"] == "nota: evidencia conservada."

