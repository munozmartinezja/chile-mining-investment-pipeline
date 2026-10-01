from __future__ import annotations

from pathlib import Path

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[1]
ALIASES_PATH = PROJECT_ROOT / "data" / "curated" / "company_aliases.csv"


def test_company_alias_catalog_has_valid_states_and_expected_aliases() -> None:
    aliases = pd.read_csv(ALIASES_PATH)

    assert aliases.columns.tolist() == ["cochilco_empresa", "alias", "estado"]
    assert set(aliases["estado"]) <= {"confirmado", "rechazado", "pendiente"}
    assert set(aliases["alias"]) == {
        "Minera Los Pelambres",
        "Minera Centinela",
        "Compañía Minera Zaldívar",
        "Minera Escondida",
        "Minera Spence",
        "Compañía Minera Cerro Colorado",
        "Minera Mantoverde",
        "Minera Santo Domingo",
        "Sociedad Contractual Minera El Abra",
        "Minera Candelaria",
        "Compañía Minera Mantos de Oro",
        "Compañía Minera del Pacífico",
        "Corporación Nacional del Cobre",
        "Empresa Nacional de Minería",
        "Doña Inés de Collahuasi",
        "Sociedad Química y Minera",
        "Pucobre",
    }


def test_company_alias_catalog_has_unique_complete_rows() -> None:
    aliases = pd.read_csv(ALIASES_PATH)

    assert not aliases[["cochilco_empresa", "alias"]].duplicated().any()
    assert aliases.notna().all().all()
    assert aliases.astype(str).apply(lambda column: column.str.strip().ne("").all()).all()
