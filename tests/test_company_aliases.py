from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
ALIASES_PATH = PROJECT_ROOT / "data" / "curated" / "company_aliases.csv"
SEA_PATH = PROJECT_ROOT / "data" / "interim" / "sea_mining.parquet"


def test_company_alias_catalog_has_valid_states_and_expected_aliases() -> None:
    aliases = pd.read_csv(ALIASES_PATH)

    assert aliases.columns.tolist() == [
        "cochilco_empresa",
        "alias",
        "estado",
        "fuente",
        "evidencia",
        "momento",
    ]
    assert set(aliases["estado"]) <= {"confirmado", "rechazado", "pendiente"}
    assert set(aliases["alias"]) == {
        "Minera Los Pelambres",
        "Minera Centinela",
        "Compañía Minera Zaldívar",
        "Minera Escondida",
        "Minera Escondida Limitada",
        "Minera Spence",
        "Compañía Minera Cerro Colorado",
        "Mantoverde",
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
        "Anglo American Sur",
    }


def test_company_alias_catalog_has_unique_rows_and_valid_provenance() -> None:
    aliases = pd.read_csv(ALIASES_PATH)

    assert not aliases[["cochilco_empresa", "alias"]].duplicated().any()
    assert aliases.drop(columns="evidencia").notna().all().all()
    assert set(aliases["momento"]) == {"antes_de_resultados", "despues_de_resultados"}
    assert aliases.loc[aliases["fuente"].eq("catalogo_inicial"), "momento"].eq(
        "antes_de_resultados"
    ).all()
    assert aliases.loc[aliases["fuente"].eq("revision_autor_2026-10"), "momento"].eq(
        "despues_de_resultados"
    ).all()


@pytest.mark.skipif(not SEA_PATH.exists(), reason="requires local SEA parquet")
def test_company_alias_evidence_ids_exist_in_local_sea_data() -> None:
    aliases = pd.read_csv(ALIASES_PATH, keep_default_na=False)
    sea_ids = set(pd.read_parquet(SEA_PATH, columns=["exp_id"])["exp_id"].astype(int))

    for evidence in aliases["evidencia"]:
        ids = [int(value) for value in evidence.split(";") if value]
        assert len(ids) <= 3
        assert set(ids) <= sea_ids


def test_operating_subsidiaries_are_confirmed_from_author_review() -> None:
    aliases = pd.read_csv(ALIASES_PATH)
    expected = {
        ("BHP", "Minera Escondida Limitada"),
        ("BHP", "Compañía Minera Cerro Colorado"),
        ("BHP", "Minera Spence"),
        ("Freeport-McMoran", "Sociedad Contractual Minera El Abra"),
        ("Anglo American", "Anglo American Sur"),
        ("Capstone Copper", "Mantoverde"),
    }
    reviewed = aliases.loc[aliases["fuente"].eq("revision_autor_2026-10")]

    assert expected.issubset(
        set(zip(reviewed["cochilco_empresa"], reviewed["alias"], strict=True))
    )
    assert reviewed["estado"].eq("confirmado").all()
