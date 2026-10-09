from __future__ import annotations

import shutil

import pytest

from cmip.config import RAW_DIR
from cmip.extract.cochilco import extract_annex_tables
from cmip.validate import (
    normalize_projects,
    reconcile_condition_mineral,
    reconcile_project_count,
    reconcile_regions,
    reconcile_temporal_total,
)


def test_project_ids_are_unique(projects) -> None:
    assert projects["project_id"].is_unique


def test_amounts_are_complete_and_nonnegative(projects) -> None:
    assert projects["inversion_musd"].notna().all()
    assert projects["inversion_musd"].ge(0).all()


def test_literal_na_mine_name_is_preserved(projects) -> None:
    assert "N/A" in set(projects["mina"])


def test_declared_and_generic_codelco_aggregations_are_flagged(projects) -> None:
    flagged = set(projects.loc[projects["nota_agregacion"], "nombre_del_proyecto"])
    assert flagged == {
        "Chuquicamata Subterránea (1)",
        "Nuevo Nivel Mina (2)",
        "Súlfuros RT Fase II (3)",
        "Otros Proyectos de Desarrollo",
        "Tranques",
    }


def test_total_investment_matches_published_portfolio(projects) -> None:
    assert projects["inversion_musd"].sum() == pytest.approx(104_549.2, abs=0.1)


def test_condition_mineral_reconciliation_has_documented_copper_shifts(
    projects, annex_tables
) -> None:
    result = reconcile_condition_mineral(projects, annex_tables[4])
    differences = {
        (row.condicion, row.mineral): row.difference_musd
        for row in result.itertuples()
        if abs(row.difference_musd) > 0.05
    }
    assert differences == {
        ("Base", "Cobre"): pytest.approx(3_678.0, abs=0.1),
        ("Probable", "Cobre"): pytest.approx(3_706.2, abs=0.1),
        ("Posible", "Cobre"): pytest.approx(-3_706.2, abs=0.1),
        ("Potencial", "Cobre"): pytest.approx(-3_678.0, abs=0.1),
    }


def test_project_count_reconciliation_documents_aggregated_rows(projects, annex_tables) -> None:
    result = reconcile_project_count(projects, annex_tables[4])
    assert result == {"table_1_rows": 59, "control_projects": 64, "difference": -5}


def test_region_reconciliation_is_exact(projects, annex_tables) -> None:
    result = reconcile_regions(projects, annex_tables[8])
    assert result["difference_musd"].abs().max() == pytest.approx(0.0, abs=0.1)


def test_temporal_total_reconciliation_preserves_rounding_difference(
    projects, annex_tables
) -> None:
    result = reconcile_temporal_total(projects, annex_tables[10])
    assert result == {
        "table_1_musd": pytest.approx(104_549.2, abs=0.01),
        "table_10_musd": pytest.approx(104_549.1, abs=0.01),
        "difference_musd": pytest.approx(0.1, abs=0.01),
    }


def test_csv_fallback_normalizes_to_same_projects(projects, tmp_path) -> None:
    for source in RAW_DIR.glob("*.csv"):
        shutil.copy2(source, tmp_path / source.name)
    csv_projects = normalize_projects(extract_annex_tables(tmp_path)[1])

    assert csv_projects["project_id"].tolist() == projects["project_id"].tolist()
    assert csv_projects["inversion_musd"].tolist() == projects["inversion_musd"].tolist()
    assert csv_projects["condicion"].tolist() == projects["condicion"].tolist()
    assert csv_projects["tipo"].tolist() == projects["tipo"].tolist()


def test_table_1_condition_and_type_shares_differ_from_control_table_basis(
    projects, annex_tables
) -> None:
    total = projects["inversion_musd"].sum()
    condition = 100 * projects.groupby("condicion")["inversion_musd"].sum() / total
    project_type = 100 * projects.groupby("tipo")["inversion_musd"].sum() / total

    assert condition.to_dict() == pytest.approx(
        {"Base": 44.4854, "Probable": 9.8519, "Posible": 9.1737, "Potencial": 36.4890},
        abs=0.0001,
    )
    assert project_type.to_dict() == pytest.approx(
        {"Nuevo": 19.5449, "Reposición": 50.2512, "Expansión": 30.2040},
        abs=0.0001,
    )
    control_type = annex_tables[5].loc[
        annex_tables[5]["Unidad"].eq("MMUS$")
        & annex_tables[5]["Columna1"].isin(["Nuevo", "Reposición", "Expansión"])
    ].set_index("Columna1")["Total"]
    assert (100 * control_type / total).to_dict() == pytest.approx(
        {"Nuevo": 19.5449, "Reposición": 46.7063, "Expansión": 33.7489},
        abs=0.0001,
    )
