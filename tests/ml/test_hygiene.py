"""Test 10: C1 isolation — no cmip.* module outside ml/ imports cmip.ml."""
from __future__ import annotations

import ast
from pathlib import Path

SRC = Path(__file__).parent.parent.parent / "src" / "cmip"


def _collect_imports(tree: ast.Module) -> list[str]:
    imports: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                imports.append(alias.name)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imports.append(node.module)
    return imports


def test_c1_modules_do_not_import_cmip_ml():
    """No source file outside src/cmip/ml/ imports cmip.ml.*"""
    violations: list[str] = []

    for py_file in SRC.rglob("*.py"):
        if "cmip/ml" in str(py_file).replace("\\", "/"):
            continue

        try:
            source = py_file.read_text(encoding="utf-8")
            tree = ast.parse(source, filename=str(py_file))
        except SyntaxError:
            continue

        imports = _collect_imports(tree)
        for imp in imports:
            if imp.startswith("cmip.ml"):
                violations.append(f"{py_file.relative_to(SRC.parent.parent)}: imports {imp}")

    assert violations == [], "\n".join(violations)
