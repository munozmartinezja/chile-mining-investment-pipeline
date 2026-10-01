from __future__ import annotations

from datetime import date

import pandas as pd
import pytest

from cmip.extract.sea import PRIVATE_COLUMNS, build_sea_frames
from cmip.match import normalize_text, rank_candidates


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

    assert ranked["exp_id"].tolist() == [10, 12, 11]
    assert ranked.iloc[0]["score"] == 100.0
    assert ranked["match_confirmado"].isna().all()
    assert 99 not in ranked["exp_id"].tolist()
