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
        abs_path = ROOT / relative_path
        if not abs_path.exists():
            continue
        text = abs_path.read_text(encoding="utf-8")
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


def _notebook_cells_text() -> list[tuple[str, str]]:
    """Return (path, combined source text) for every cell in tracked notebooks."""
    import json

    result = []
    for relative_path in _tracked_text_files():
        if relative_path.suffix != ".ipynb":
            continue
        nb = json.loads((ROOT / relative_path).read_bytes())
        combined = "\n".join(
            "".join(cell.get("source", []))
            for cell in nb.get("cells", [])
        )
        result.append((str(relative_path), combined))
    return result


def test_readme_and_notebooks_no_isolated_reviewer_initial() -> None:
    """README.md, data/powerbi/README.md and notebook cells must not contain a
    bare 'J' word boundary match, except inside the author attribution 'J. A.'."""
    isolated_j = re.compile(r"\bJ\b")
    author_ok = re.compile(r"\bJ\.\s*A\.")

    targets: list[tuple[str, str]] = [
        ("README.md", (ROOT / "README.md").read_text(encoding="utf-8")),
        (
            "data/powerbi/README.md",
            (ROOT / "data" / "powerbi" / "README.md").read_text(encoding="utf-8"),
        ),
    ]
    targets.extend(_notebook_cells_text())

    offenders: list[str] = []
    for path, text in targets:
        # Strip out "J. A." occurrences before checking
        scrubbed = author_ok.sub("", text)
        if isolated_j.search(scrubbed):
            offenders.append(path)

    assert offenders == [], f"Isolated reviewer initial 'J' found in: {offenders}"


def test_readme_and_notebooks_no_reviewer_initial_suffix() -> None:
    """README.md, data/powerbi/README.md and notebook cells must not contain _J
    (uppercase J preceded by underscore at a word boundary)."""
    pattern = re.compile(r"_J\b")

    targets: list[tuple[str, str]] = [
        ("README.md", (ROOT / "README.md").read_text(encoding="utf-8")),
        (
            "data/powerbi/README.md",
            (ROOT / "data" / "powerbi" / "README.md").read_text(encoding="utf-8"),
        ),
    ]
    targets.extend(_notebook_cells_text())

    offenders: list[str] = []
    for path, text in targets:
        if pattern.search(text):
            offenders.append(path)

    assert offenders == [], f"Pattern '_J' found in: {offenders}"


def test_english_section_no_spanish_phrases() -> None:
    """The English section of README.md must not contain certain Spanish phrases."""
    text = (ROOT / "README.md").read_text(encoding="utf-8")
    english_marker = "## English"
    idx = text.find(english_marker)
    assert idx != -1, "English section not found in README.md"
    english_text = text[idx:]

    forbidden = ["La supervivencia", "decisiones", "cruce"]
    found = [p for p in forbidden if p in english_text]
    assert found == [], f"Spanish phrases found in English section: {found}"


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
