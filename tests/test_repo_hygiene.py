from __future__ import annotations

import re
import subprocess
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
CHECKLIST = ROOT / "docs" / "validation_checklist.csv"
EXCLUDED_SUFFIXES = {".pdf", ".png", ".xlsx"}
FORBIDDEN_TOOL_NAMES = (
    "Clau" + "de",
    "Co" + "dex",
    "Chat" + "GPT",
)


def _tracked_text_files() -> list[Path]:
    output = subprocess.run(
        ["git", "ls-files", "-z"],
        cwd=ROOT,
        check=True,
        capture_output=True,
    ).stdout
    paths = [Path(value.decode("utf-8")) for value in output.split(b"\0") if value]
    return [
        path
        for path in paths
        if path.name != "uv.lock" and path.suffix.casefold() not in EXCLUDED_SUFFIXES
    ]


def test_tracked_text_files_do_not_name_workflow_tools() -> None:
    pattern = re.compile("|".join(map(re.escape, FORBIDDEN_TOOL_NAMES)), re.IGNORECASE)
    offenders: list[str] = []
    for relative_path in _tracked_text_files():
        text = (ROOT / relative_path).read_text(encoding="utf-8")
        if pattern.search(text):
            offenders.append(str(relative_path))

    assert offenders == []


def test_validation_checklist_has_public_schema_and_no_reviewer_initial() -> None:
    checklist = pd.read_csv(CHECKLIST, keep_default_na=False)

    assert not {"respuesta_J", "fuente_J", "url_busqueda"}.intersection(checklist.columns)
    assert {"decision", "fuente_decision"}.issubset(checklist.columns)
    isolated_initial = re.compile(r"(?<!\w)J(?!\w)")
    offenders = checklist.apply(
        lambda column: column.astype(str).str.contains(isolated_initial)
    )
    assert not offenders.to_numpy().any()


def test_gitignore_covers_private_inputs_and_build_notes() -> None:
    ignored_paths = (
        "data/raw/sea_transparencia/example.csv",
        "docs/powerbi/model.md",
        "PROMPT_example.md",
    )
    result = subprocess.run(
        ["git", "check-ignore", "--no-index", "--stdin"],
        cwd=ROOT,
        check=False,
        input="\n".join(ignored_paths) + "\n",
        text=True,
        capture_output=True,
    )

    assert result.returncode == 0
    assert result.stdout.splitlines() == list(ignored_paths)
