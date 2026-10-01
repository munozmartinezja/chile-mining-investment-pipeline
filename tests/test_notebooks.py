from __future__ import annotations

import json
from pathlib import Path

import pytest

NOTEBOOKS = Path(__file__).resolve().parents[1] / "notebooks"


@pytest.mark.parametrize("name", ["00_data_checks.ipynb", "01_match_review.ipynb"])
def test_versioned_notebooks_do_not_store_outputs_or_execution_counts(name: str) -> None:
    notebook = json.loads((NOTEBOOKS / name).read_text(encoding="utf-8"))
    code_cells = [cell for cell in notebook["cells"] if cell["cell_type"] == "code"]

    assert all(cell.get("outputs", []) == [] for cell in code_cells)
    assert all(cell.get("execution_count") is None for cell in code_cells)
