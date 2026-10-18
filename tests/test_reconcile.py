from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pandas as pd
import pytest

from cmip.reconcile import (
    apply_official_at_cutoff,
    build_claim_impact,
    build_reconciliation_summary,
    load_reconciliation_summary,
    reconcile_sea,
    resolve_reconciliation_summary,
    write_reconciliation_outputs,
    write_reconciliation_summary,
)
from cmip.sea_oficial import load_sea_oficial

ROOT = Path(__file__).resolve().parents[1]
OFFICIAL_PATH = ROOT / "data/raw/sea_transparencia/sea_transparencia_proyectos_mineros_20261013.csv"
NUESTRA_PATH = ROOT / "data/interim/sea_mining.parquet"
SUMMARY_PATH = ROOT / "docs/reconciliation_sea_oficial_summary.json"


def _synthetic_frames() -> tuple[pd.DataFrame, pd.DataFrame]:
    nuestra = pd.DataFrame(
        {
            "exp_id": [1, 2],
            "instrumento": ["DIA", "DIA"],
            "tipologia": ["i1", "i2"],
            "estado": ["En Calificación", "Aprobado"],
            "fecha_ingreso": pd.to_datetime(["2020-01-01", "2021-01-01"]),
            "fecha_cierre": pd.to_datetime([None, "2021-02-01"]),
            "inversion_musd": [10.0, 20.0],
            "admitido": [True, True],
            "fecha_inconsistente": [False, False],
            "exp_nombre": ["Proyecto uno", "Proyecto dos"],
            "evento": ["en_tramite", "aprobado"],
            "duracion_dias": pd.Series([100, 31], dtype="Int64"),
            "titular_nombre": ["Titular nuestra secreto", "Otro titular"],
            "empresa_nombre": ["Empresa nuestra secreta", "Otra empresa"],
        }
    )
    oficial = pd.DataFrame(
        {
            "exp_id": pd.Series([1, 3], dtype="int64"),
            "instrumento": ["EIA", "DIA"],
            "tipologia": ["i4", "i3"],
            "estado": ["Aprobado", "En Calificación"],
            "fecha_ingreso": pd.to_datetime(["2020-01-02", "2026-09-01"]),
            "fecha_cierre": pd.to_datetime(["2020-03-01", None]),
            "inversion_musd": [11.0, 30.0],
            "titular": ["Titular oficial secreto", "Titular posterior"],
            "empresa": ["Empresa oficial secreta", "Empresa posterior"],
        }
    )
    return nuestra, oficial


def test_reconcile_sea_synthetic_covers_every_difference_category() -> None:
    nuestra, oficial = _synthetic_frames()

    differences = reconcile_sea(nuestra, oficial)

    assert differences.columns.tolist() == [
        "exp_id",
        "campo",
        "valor_nuestro",
        "valor_oficial",
        "posterior_al_corte",
        "en_poblacion_995",
    ]
    assert set(differences["campo"]) == {
        "presencia_oficial",
        "presencia_nuestra",
        "instrumento",
        "tipologia",
        "estado",
        "fecha_ingreso",
        "fecha_cierre",
        "inversion_musd",
    }
    common = differences.loc[differences["exp_id"].eq(1)]
    assert common["en_poblacion_995"].all()
    assert not common["posterior_al_corte"].any()
    posterior = differences.loc[differences["exp_id"].eq(3)].iloc[0]
    assert posterior["campo"] == "presencia_nuestra"
    assert posterior["posterior_al_corte"]


def test_reconcile_sea_respects_half_mmusd_tolerance() -> None:
    nuestra, oficial = _synthetic_frames()
    nuestra = nuestra.loc[nuestra["exp_id"].eq(1)].copy()
    oficial = oficial.loc[oficial["exp_id"].eq(1)].copy()
    nuestra["inversion_musd"] = 10.0
    oficial["inversion_musd"] = 10.5

    differences = reconcile_sea(nuestra, oficial)

    assert "inversion_musd" not in set(differences["campo"])


def test_apply_official_at_cutoff_censors_later_closures() -> None:
    nuestra, oficial = _synthetic_frames()
    oficial.loc[oficial["exp_id"].eq(1), "fecha_cierre"] = pd.Timestamp("2026-09-22")

    result = apply_official_at_cutoff(nuestra, oficial, corte="2026-08-25")

    row = result.loc[result["exp_id"].eq(1)].iloc[0]
    assert row["estado"] == "En Calificación"
    assert row["evento"] == "en_tramite"
    assert pd.isna(row["fecha_cierre"])
    assert row["fecha_ingreso"] == pd.Timestamp("2020-01-02")
    assert row["inversion_musd"] == 11.0
    assert row["duracion_dias"] == (pd.Timestamp("2026-08-25") - row["fecha_ingreso"]).days


def test_reconciliation_outputs_do_not_leak_private_columns_or_values(tmp_path: Path) -> None:
    nuestra, oficial = _synthetic_frames()
    differences = reconcile_sea(nuestra, oficial)
    csv_path = tmp_path / "reconciliation.csv"
    md_path = tmp_path / "reconciliation.md"
    summary_path = tmp_path / "reconciliation.json"
    official_path = tmp_path / "official.csv"
    official_path.write_text(
        "Titular oficial secreto;Empresa oficial secreta\n", encoding="utf-8"
    )

    write_reconciliation_outputs(differences, csv_path=csv_path, markdown_path=md_path)
    summary = build_reconciliation_summary(
        nuestra,
        oficial,
        official_path=official_path,
        corte="2026-08-25",
    )
    write_reconciliation_summary(summary, summary_path)

    content = (
        csv_path.read_text(encoding="utf-8")
        + md_path.read_text(encoding="utf-8")
        + summary_path.read_text(encoding="utf-8")
    )
    lowered = content.casefold()
    assert "titular" not in lowered
    assert "empresa" not in lowered
    for private_value in (
        "Titular nuestra secreto",
        "Empresa nuestra secreta",
        "Titular oficial secreto",
        "Empresa oficial secreta",
    ):
        assert private_value not in content


@pytest.mark.skipif(
    not (OFFICIAL_PATH.exists() and NUESTRA_PATH.exists()),
    reason="requires local official SEA response and local SEA parquet",
)
def test_real_reconciliation_matches_official_response_categories() -> None:
    nuestra = pd.read_parquet(NUESTRA_PATH)
    oficial = load_sea_oficial(OFFICIAL_PATH)

    differences = reconcile_sea(nuestra, oficial)
    counts = differences.groupby("campo").size().to_dict()

    assert counts == {
        "estado": 2,
        "fecha_cierre": 2,
        "fecha_ingreso": 2,
        "presencia_nuestra": 4,
    }
    assert int((~differences["posterior_al_corte"]).sum()) == 2
    previous = differences.loc[~differences["posterior_al_corte"]]
    assert set(previous["campo"]) == {"fecha_ingreso"}
    assert int(previous["en_poblacion_995"].sum()) == 1


@pytest.mark.skipif(
    not (OFFICIAL_PATH.exists() and NUESTRA_PATH.exists()),
    reason="requires local official SEA response and local SEA parquet",
)
def test_versioned_summary_matches_real_reconciliation_and_official_hash() -> None:
    nuestra = pd.read_parquet(NUESTRA_PATH)
    oficial = load_sea_oficial(OFFICIAL_PATH)

    stored = load_reconciliation_summary(SUMMARY_PATH)
    calculated = build_reconciliation_summary(
        nuestra,
        oficial,
        official_path=OFFICIAL_PATH,
        corte="2026-08-25",
    )

    assert stored == calculated
    assert stored["sha256_archivo_oficial"] == hashlib.sha256(
        OFFICIAL_PATH.read_bytes()
    ).hexdigest()


@pytest.mark.skipif(
    not (OFFICIAL_PATH.exists() and NUESTRA_PATH.exists()),
    reason="requires local official SEA response and local SEA parquet",
)
@pytest.mark.parametrize(
    ("field", "altered_value"),
    [
        ("expedientes_coinciden_n", 1_962),
        ("sha256_archivo_oficial", "0" * 64),
    ],
)
def test_altered_summary_is_rejected_explicitly(
    tmp_path: Path, field: str, altered_value: object
) -> None:
    altered = load_reconciliation_summary(SUMMARY_PATH)
    altered[field] = altered_value
    altered_path = tmp_path / "altered-summary.json"
    altered_path.write_text(json.dumps(altered), encoding="utf-8")

    with pytest.raises(ValueError, match=rf"resumen.*no coincide.*{field}"):
        resolve_reconciliation_summary(
            pd.read_parquet(NUESTRA_PATH),
            official_path=OFFICIAL_PATH,
            summary_path=altered_path,
        )


@pytest.mark.skipif(
    not (
        OFFICIAL_PATH.exists()
        and NUESTRA_PATH.exists()
        and (ROOT / "data/processed/cochilco_seia.parquet").exists()
    ),
    reason="requires local official SEA response and local analysis data",
)
def test_official_recalculation_preserves_every_published_rounded_claim(recwarn) -> None:  # noqa: ANN001
    impact = build_claim_impact(
        pd.read_parquet(NUESTRA_PATH),
        load_sea_oficial(OFFICIAL_PATH),
    )

    assert len(impact) >= 60
    assert not impact["cambia_al_redondeo"].any(), impact.loc[impact["cambia_al_redondeo"]].to_dict(
        "records"
    )
    assert not [warning for warning in recwarn if "Tied event times" in str(warning.message)]
