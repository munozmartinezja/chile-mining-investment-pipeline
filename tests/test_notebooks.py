from __future__ import annotations

import json
from pathlib import Path

import pytest

NOTEBOOKS = Path(__file__).resolve().parents[1] / "notebooks"


@pytest.mark.parametrize(
    "name", ["00_data_checks.ipynb", "01_match_review.ipynb", "02_validation.ipynb"]
)
def test_versioned_notebooks_do_not_store_outputs_or_execution_counts(name: str) -> None:
    notebook = json.loads((NOTEBOOKS / name).read_text(encoding="utf-8"))
    code_cells = [cell for cell in notebook["cells"] if cell["cell_type"] == "code"]

    assert all(cell.get("outputs", []) == [] for cell in code_cells)
    assert all(cell.get("execution_count") is None for cell in code_cells)


def test_validation_notebook_ends_with_verified_claims_and_complete_checklist_gate() -> None:
    notebook = json.loads((NOTEBOOKS / "02_validation.ipynb").read_text(encoding="utf-8"))
    last_cell = notebook["cells"][-1]
    source = "".join(last_cell["source"])

    assert last_cell["cell_type"] == "code"
    assert "GATE" in source
    assert 'claims["estado"].eq("verificada").all()' in source
    assert "assert len(checklist) == 61" in source
    assert "assert not pending.any()" in source


def test_validation_notebook_resolves_checklist_when_launched_from_notebooks(
    monkeypatch,
) -> None:  # noqa: ANN001
    notebook = json.loads((NOTEBOOKS / "02_validation.ipynb").read_text(encoding="utf-8"))
    setup_source = "".join(notebook["cells"][1]["source"])
    namespace: dict[str, object] = {}
    monkeypatch.chdir(NOTEBOOKS)

    exec(compile(setup_source, "02_validation.ipynb", "exec"), namespace)

    assert namespace["CHECKLIST"] == NOTEBOOKS.parent / "docs/validation_checklist.csv"
