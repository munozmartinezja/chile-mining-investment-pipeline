from __future__ import annotations

from datetime import date

import pandas as pd
import pytest

from cmip.extract.sea import PRIVATE_COLUMNS, _hyper_select_expression, build_sea_frames
from cmip.match import normalize_text, project_name_score, rank_candidates


def _ingresados() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "exp_id": [1, 2, 3],
            "exp_nombre": ["Proyecto Cobre Norte", "Mina Sur", "Proyecto Solar"],
            "reg_romano": ["II", "III", "IV"],
            "work_alias": ["DIA", "EIA", "DIA"],
            "texp_letra": ["i", "i", "c"],
            "seco_nombre": ["Minería", "Minería", "Energía"],
            "est_nombre": ["Aprobado", "En Calificación", "Rechazado"],
            "MMU": [100.0, 250.0, 50.0],
            "exp_fpres": pd.to_datetime(["2020-01-01", "2025-01-01", "2021-01-01"]),
            "exp_fcierre": pd.to_datetime(["2020-01-11", None, "2021-02-01"]),
            "titular_nombre": ["Compañía Uno", "Minera Dos", "Solar Tres"],
            "empresa_nombre": ["Cía. Uno S.A.", "Minera Dos Ltda.", "Solar Tres"],
            "encargado_nombre": ["private", "private", "private"],
            "encargado_rut": ["private", "private", "private"],
            "titular_rut": ["private", "private", "private"],
        }
    )


def test_build_sea_frames_drops_private_columns_and_computes_survival() -> None:
    plazos = pd.DataFrame(
        {
            "EXP_ID": [1],
            "EVAL_HABIL": [7],
            "SUS_HABIL": [1],
            "SUSSEA_HABIL": [0],
            "DIAS_CORRIDOS": [10],
            "EXP_FECHA_RCA": pd.to_datetime(["2020-01-10"]),
            "EXP_NRO_RCA": [42],
        }
    )

    projects, mining = build_sea_frames(_ingresados(), plazos, cutoff=date(2026, 9, 30))

    assert PRIVATE_COLUMNS.isdisjoint(projects.columns)
    assert projects.loc[projects.exp_id == 1, "duracion_dias"].item() == 10
    assert projects.loc[projects.exp_id == 2, "duracion_dias"].item() == 637
    assert projects.loc[projects.exp_id == 1, "evento"].item() == "aprobado"
    assert projects.loc[projects.exp_id == 1, "admitido"].item() is not False
    assert projects.loc[projects.exp_id == 1, "eval_habil"].item() == 7
    assert mining["exp_id"].tolist() == [1, 2]


def test_build_sea_frames_rejects_an_unmapped_state() -> None:
    ingresados = _ingresados().iloc[[0]].copy()
    ingresados["est_nombre"] = "Estado inventado"

    with pytest.raises(ValueError, match="Unmapped SEA states"):
        build_sea_frames(ingresados, pd.DataFrame(), cutoff=date(2026, 9, 30))


def test_hyper_date_and_timestamp_columns_are_cast_to_text() -> None:
    from tableauhyperapi import SqlType, TableDefinition

    date_column = TableDefinition.Column("exp_fpres", SqlType.date())
    timestamp_column = TableDefinition.Column("exp_fcierre", SqlType.timestamp())
    text_column = TableDefinition.Column("exp_nombre", SqlType.text())

    assert _hyper_select_expression(date_column) == (
        'CAST("exp_fpres" AS TEXT) AS "exp_fpres"'
    )
    assert _hyper_select_expression(timestamp_column) == (
        'CAST("exp_fcierre" AS TEXT) AS "exp_fcierre"'
    )
    assert _hyper_select_expression(text_column) == '"exp_nombre"'


def test_build_sea_frames_rejects_an_invalid_non_null_date() -> None:
    ingresados = _ingresados()
    ingresados["exp_fpres"] = ingresados["exp_fpres"].astype("object")
    ingresados.loc[0, "exp_fpres"] = "not-a-date"

    with pytest.raises(ValueError, match="Invalid date value in exp_fpres"):
        build_sea_frames(ingresados, pd.DataFrame(), cutoff=date(2026, 9, 30))


def test_build_sea_frames_keeps_allowed_inconsistent_dates_without_duration() -> None:
    ingresados = _ingresados().iloc[[0]].copy()
    ingresados["est_nombre"] = "Desistido"
    ingresados["exp_fcierre"] = pd.to_datetime(["2019-12-31"])

    projects, _ = build_sea_frames(ingresados, pd.DataFrame())

    assert projects["fecha_inconsistente"].item() is True
    assert pd.isna(projects["duracion_dias"].item())
    assert projects["fecha_cierre"].item() == pd.Timestamp("2019-12-31")
    assert projects["fecha_ingreso"].item() == pd.Timestamp("2020-01-01")


def test_build_sea_frames_rejects_inconsistent_dates_in_timing_events() -> None:
    ingresados = _ingresados().iloc[[0]].copy()
    ingresados["exp_fcierre"] = pd.to_datetime(["2019-12-31"])

    with pytest.raises(ValueError, match="date inconsistencies in timing-analysis events"):
        build_sea_frames(ingresados, pd.DataFrame())


@pytest.mark.parametrize(
    ("source", "expected"),
    [
        ("Cía. Minera Doña Inés", "compania minera dona ines"),
        ("MIN. Los Cóndores S.A.", "minera los condores sa"),
        ("Soc. Contractual Minera", "sociedad contractual minera"),
    ],
)
def test_normalize_text_expands_abbreviations_and_strips_accents(
    source: str, expected: str
) -> None:
    assert normalize_text(source) == expected


def test_rank_candidates_filters_region_and_orders_top_three() -> None:
    cochilco = pd.DataFrame(
        {
            "project_id": ["c1"],
            "nombre_del_proyecto": ["Continuidad Mina Cóndor"],
            "empresa": ["Cía. Minera Andina"],
            "region": ["Antofagasta"],
        }
    )
    sea = pd.DataFrame(
        {
            "exp_id": [10, 11, 12, 13, 99],
            "exp_nombre": [
                "Continuidad Mina Condor",
                "Ampliación Mina Condor",
                "Proyecto Distinto",
                "Otro proyecto",
                "Continuidad Mina Condor",
            ],
            "empresa_nombre": [
                "Compañía Minera Andina",
                "Empresa X",
                "Cía Minera Andina",
                "Empresa Y",
                "Compañía Minera Andina",
            ],
            "titular_nombre": [None, None, None, None, None],
            "estado": ["Aprobado"] * 5,
            "fecha_ingreso": pd.to_datetime(["2020-01-01"] * 5),
            "region": ["II", "II", "II", "II", "III"],
            "seco_nombre": ["Minería"] * 5,
        }
    )

    ranked = rank_candidates(cochilco, sea)

    assert ranked["exp_id"].tolist() == [10, 12]
    assert ranked.iloc[0]["score"] == 100.0
    assert ranked["empresa_no_coincide"].eq(False).all()
    assert ranked["match_confirmado"].isna().all()
    assert 99 not in ranked["exp_id"].tolist()


def test_rosario_fourth_line_does_not_match_pampa_pabellon_tailings() -> None:
    score = project_name_score(
        "4ª Línea: Nueva concentradora en Rosario",
        "Continuidad Relaves Espesados Pampa Pabellón",
    )

    assert score < 60


def test_chuquicamata_subterranea_top_match_is_not_sondajes() -> None:
    cochilco = pd.DataFrame(
        {
            "project_id": ["chuqui"],
            "nombre_del_proyecto": ["Chuquicamata Subterránea"],
            "empresa": ["Codelco"],
            "region": ["Antofagasta"],
        }
    )
    sea = pd.DataFrame(
        {
            "exp_id": [1, 2],
            "exp_nombre": [
                "Proyecto Chuquicamata Subterránea",
                "Sondajes para Proyecto Chuquicamata Subterránea",
            ],
            "empresa_nombre": ["Codelco", "Codelco"],
            "titular_nombre": ["Codelco", "Codelco"],
            "estado": ["Aprobado", "Aprobado"],
            "fecha_ingreso": pd.to_datetime(["2020-01-01", "2020-01-01"]),
            "region": ["II", "II"],
            "seco_nombre": ["Minería", "Minería"],
        }
    )

    ranked = rank_candidates(cochilco, sea)

    assert "sondajes" not in ranked.iloc[0]["sea_nombre"].casefold()


def test_rank_candidates_keeps_project_when_region_has_no_candidates() -> None:
    cochilco = pd.DataFrame(
        {
            "project_id": ["missing"],
            "nombre_del_proyecto": ["Proyecto sin expediente"],
            "empresa": ["Empresa sin expediente"],
            "region": ["Tarapacá"],
        }
    )
    sea = pd.DataFrame(
        {
            "exp_id": [1],
            "exp_nombre": ["Otro proyecto"],
            "empresa_nombre": ["Otra empresa"],
            "titular_nombre": ["Otra empresa"],
            "estado": ["Aprobado"],
            "fecha_ingreso": pd.to_datetime(["2020-01-01"]),
            "region": ["II"],
            "seco_nombre": ["Minería"],
        }
    )

    ranked = rank_candidates(cochilco, sea)

    assert ranked["cochilco_id"].tolist() == ["missing"]
    assert ranked["match_tipo"].tolist() == ["sin_candidato"]


def test_rank_candidates_rejects_a_matched_sea_record_without_fecha_ingreso() -> None:
    cochilco = pd.DataFrame(
        {
            "project_id": ["missing-date"],
            "nombre_del_proyecto": ["Proyecto Cobre"],
            "empresa": ["Minera Uno"],
            "region": ["Antofagasta"],
        }
    )
    sea = pd.DataFrame(
        {
            "exp_id": [1],
            "exp_nombre": ["Proyecto Cobre"],
            "empresa_nombre": ["Minera Uno"],
            "titular_nombre": ["Minera Uno"],
            "estado": ["Aprobado"],
            "fecha_ingreso": [pd.NaT],
            "region": ["II"],
            "seco_nombre": ["Minería"],
        }
    )

    with pytest.raises(ValueError, match="SEA candidate 1 has no fecha_ingreso"):
        rank_candidates(cochilco, sea)
