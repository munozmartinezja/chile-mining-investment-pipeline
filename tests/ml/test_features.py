"""Tests 3–5, 8, A1, A2, A4, A5: features, leakage, privacy, coef names."""
from __future__ import annotations

import pandas as pd
import pytest


def _make_df(rows: list[dict], date_cols: list[str] | None = None) -> pd.DataFrame:
    df = pd.DataFrame(rows)
    for col in date_cols or []:
        df[col] = pd.to_datetime(df[col])
    return df


# ── Test 3: titular features — no future leakage ──────────────────────────────

def test_titular_features_no_future_leakage():
    """A later project from the same titular does not affect an earlier one."""
    from cmip.ml.features import add_titular_features

    sea = _make_df([
        {
            "exp_id": "T1",
            "titular_nombre": "Empresa X",
            "fecha_ingreso": "2015-01-01",
            "fecha_cierre": "2016-06-01",
            "evento": "aprobado",
            "seco_nombre": "Minería",
        },
        {
            "exp_id": "T2",
            "titular_nombre": "Empresa X",
            "fecha_ingreso": "2017-03-01",
            "fecha_cierre": None,
            "evento": None,
            "seco_nombre": "Minería",
        },
    ], date_cols=["fecha_ingreso", "fecha_cierre"])

    df = _make_df([{
        "exp_id": "T1",
        "titular_nombre": "Empresa X",
        "fecha_ingreso": "2015-01-01",
    }], date_cols=["fecha_ingreso"])

    result = add_titular_features(df, sea)
    assert result.iloc[0]["titular_n_previos"] == 0


def test_titular_same_day_close_not_counted():
    """A closure on the same day as the new intake is not counted as prior closed."""
    from cmip.ml.features import add_titular_features

    sea = _make_df([
        {
            "exp_id": "T3",
            "titular_nombre": "Empresa Y",
            "fecha_ingreso": "2016-01-01",
            "fecha_cierre": "2018-05-01",
            "evento": "aprobado",
            "seco_nombre": "Minería",
        },
    ], date_cols=["fecha_ingreso", "fecha_cierre"])

    df = _make_df([{
        "exp_id": "NEW",
        "titular_nombre": "Empresa Y",
        "fecha_ingreso": "2018-05-01",
    }], date_cols=["fecha_ingreso"])

    result = add_titular_features(df, sea)
    # T3 ingreso < 2018-05-01 (strict), but fecha_cierre == t → not counted as prior closed
    assert result.iloc[0]["titular_n_previos"] == 1  # T3's ingreso is strictly prior
    assert result.iloc[0]["titular_aprob_previas"] == 0  # fecha_cierre == t


# ── Test 4: carga sea region ──────────────────────────────────────────────────

def test_carga_sea_region_counts_open():
    """Only open-at-t projects in same region are counted."""
    from cmip.ml.features import add_carga_sea_region

    sea = _make_df([
        # Open at 2018-01-01 in Atacama
        {"exp_id": "S1", "region": "Atacama", "fecha_ingreso": "2015-01-01",
         "fecha_cierre": None},
        # Closed before t
        {"exp_id": "S2", "region": "Atacama", "fecha_ingreso": "2014-01-01",
         "fecha_cierre": "2017-06-01"},
        # Different region
        {"exp_id": "S3", "region": "Antofagasta", "fecha_ingreso": "2015-01-01",
         "fecha_cierre": None},
        # Closed after t → open at t
        {"exp_id": "S4", "region": "Atacama", "fecha_ingreso": "2016-01-01",
         "fecha_cierre": "2019-01-01"},
    ], date_cols=["fecha_ingreso", "fecha_cierre"])

    df = _make_df([{
        "exp_id": "NEW",
        "region": "Atacama",
        "fecha_ingreso": "2018-01-01",
    }], date_cols=["fecha_ingreso"])

    result = add_carga_sea_region(df, sea)
    assert result.iloc[0]["carga_sea_region"] == 2  # S1 and S4


# ── Test 5: leakage guard ─────────────────────────────────────────────────────

def test_leakage_columns_raise():
    """build_feature_matrix raises ValueError if any LEAKAGE_COLUMNS present."""
    from cmip.ml.features import ALL_FEATURES, LEAKAGE_COLUMNS, build_feature_matrix

    # Pick a leakage col that is not already in ALL_FEATURES
    leakage_col = next(iter(LEAKAGE_COLUMNS - set(ALL_FEATURES)))  # noqa: E501
    n = 5
    data = {feat: [0] * n for feat in ALL_FEATURES}
    data[leakage_col] = ["x"] * n
    df = pd.DataFrame(data)
    with pytest.raises(ValueError, match="Leakage"):
        build_feature_matrix(df)


# ── Test 8: privacy — output refuses titular_nombre ──────────────────────────

def test_build_ml_population_no_private_output():
    """build_ml_population output must not contain titular_nombre."""
    from cmip.config import SEA_DATA_CURRENCY_DATE
    from cmip.ml.dataset import HORIZON_TD, build_ml_population

    cutoff = pd.Timestamp(SEA_DATA_CURRENCY_DATE)
    ingreso = cutoff - HORIZON_TD - pd.to_timedelta(10, unit="D")

    pop = pd.DataFrame([{
        "exp_id": "P1",
        "fecha_ingreso": ingreso,
        "fecha_cierre": ingreso + pd.to_timedelta(400, unit="D"),
        "evento": "aprobado",
        "duration_days": 400.0,
        "instrumento": "DIA",
        "tipologia": "Proyecto",
        "region": "Atacama",
        "macro_zona": "Norte",
        "titular_nombre": "Empresa Privada SA",
        "inversion_musd": 100.0,
    }])
    pop["fecha_ingreso"] = pd.to_datetime(pop["fecha_ingreso"])
    pop["fecha_cierre"] = pd.to_datetime(pop["fecha_cierre"])

    sea = pop[
        ["exp_id", "titular_nombre", "fecha_ingreso", "fecha_cierre", "evento"]
    ].copy()
    sea["instrumento"] = "DIA"
    sea["region"] = "Atacama"
    sea["tipologia"] = "Proyecto"
    sea["inversion_musd"] = 100.0
    sea["seco_nombre"] = "Minería"

    result = build_ml_population(pop, sea_projects=sea)
    assert "titular_nombre" not in result.columns
    assert "empresa_nombre" not in result.columns
    assert "exp_nombre" not in result.columns


# ── A1: coefficient names must be readable ────────────────────────────────────

def test_logit_coefs_readable_names():
    """A1: extract_logit_coefs uses real feature names, not f0..fN."""
    import re

    import numpy as np

    sklearn = pytest.importorskip("sklearn")  # noqa: F841

    from cmip.ml.models import build_logistic_pipeline, extract_logit_coefs

    rng = np.random.default_rng(0)
    n = 100
    df = pd.DataFrame({
        "log_inversion": rng.uniform(2, 8, n),
        "inversion_faltante": rng.integers(0, 2, n),
        "anio_ingreso": rng.integers(2010, 2022, n),
        "mes_sin": rng.uniform(-1, 1, n),
        "mes_cos": rng.uniform(-1, 1, n),
        "titular_n_previos": rng.integers(0, 5, n),
        "titular_aprob_previas": rng.integers(0, 3, n),
        "titular_cierres_neg_previos": rng.integers(0, 2, n),
        "reingreso_probable": rng.integers(0, 2, n),
        "carga_sea_region": rng.integers(0, 20, n),
        "instrumento": rng.choice(["DIA", "EIA"], n),
        "tipologia": rng.choice(["Tipo_A", "Tipo_B", "Tipo_C"], n),
        "macro_zona": rng.choice(["Norte", "Sur"], n),
        "region": rng.choice(["Atacama", "Antofagasta"], n),
    })
    y = pd.Series(rng.integers(0, 2, n), name="y")

    pipe = build_logistic_pipeline()
    pipe.fit(df, y)
    coefs = extract_logit_coefs(pipe)

    names = coefs["feature"].tolist()
    # Must contain readable prefix names
    assert any(n.startswith("num__log_inversion") for n in names)
    assert any("cat_plain__instrumento_" in n for n in names)
    # Must not be f0..fN generic names
    assert not any(re.match(r"^f\d+$", n) for n in names)


# ── A2: run_oof fails if dataset has a leakage column ─────────────────────────

def test_run_oof_fails_with_leakage_column(monkeypatch):
    """A2: run_oof raises ValueError when ALL_FEATURES contains a leakage column."""
    import datetime

    import numpy as np

    sklearn = pytest.importorskip("sklearn")  # noqa: F841

    from cmip.ml import features as feat_module
    from cmip.ml.evaluate import run_oof
    from cmip.ml.split import temporal_split

    rows = []
    for year in range(2010, 2025):
        for i in range(40):
            rows.append({
                "exp_id": f"E{len(rows):04d}",
                "fecha_ingreso": pd.Timestamp(datetime.date(year, (i % 12) + 1, 1)),
                "instrumento": "DIA" if i % 3 else "EIA",
                "tipologia": "Tipo_A",
                "macro_zona": "Norte",
                "region": "Atacama",
                "y": int(np.random.default_rng(i).integers(0, 2)),
                "anio_ingreso": year,
                "mes_sin": 0.0,
                "mes_cos": 1.0,
                "log_inversion": 4.6,
                "inversion_faltante": 0,
                "titular_n_previos": 0,
                "titular_aprob_previas": 0,
                "titular_cierres_neg_previos": 0,
                "reingreso_probable": 0,
                "carga_sea_region": 5,
                "evento": "aprobado",  # leakage column injected into dataset
            })

    dataset = pd.DataFrame(rows)
    dataset["fecha_ingreso"] = pd.to_datetime(dataset["fecha_ingreso"])

    # Monkeypatch ALL_FEATURES to include the leakage column
    original = feat_module.ALL_FEATURES
    monkeypatch.setattr(feat_module, "ALL_FEATURES", original + ["evento"])

    split = temporal_split(dataset)
    with pytest.raises(ValueError, match="Leakage"):
        run_oof(dataset, split)


# ── A4: null titular → all four features = 0 ─────────────────────────────────

def test_null_titular_features_are_zero():
    """A4: a project with None titular_nombre gets 0 in all titular features."""
    from cmip.ml.features import add_titular_features

    sea = _make_df([
        {
            "exp_id": "S1",
            "titular_nombre": "Empresa Z",
            "fecha_ingreso": "2015-01-01",
            "fecha_cierre": "2016-01-01",
            "evento": "aprobado",
            "seco_nombre": "Minería",
        },
    ], date_cols=["fecha_ingreso", "fecha_cierre"])

    df = _make_df([{
        "exp_id": "N1",
        "titular_nombre": None,
        "fecha_ingreso": "2018-01-01",
    }], date_cols=["fecha_ingreso"])

    result = add_titular_features(df, sea)
    row = result.iloc[0]
    assert row["titular_n_previos"] == 0
    assert row["titular_aprob_previas"] == 0
    assert row["titular_cierres_neg_previos"] == 0
    assert row["reingreso_probable"] == 0


# ── A5: reingreso_probable uses only mining sector ────────────────────────────

def test_reingreso_probable_mining_only():
    """A5: a non-mining negative closure does not trigger reingreso_probable=1."""
    from cmip.ml.features import add_titular_features

    # Non-mining negative closure in the 365-day window
    sea = _make_df([
        {
            "exp_id": "NM1",
            "titular_nombre": "Empresa M",
            "fecha_ingreso": "2019-01-01",
            "fecha_cierre": "2019-06-01",
            "evento": "desistido_o_abandonado",
            "seco_nombre": "Energía",  # not Minería
        },
        {
            "exp_id": "M1",
            "titular_nombre": "Empresa M",
            "fecha_ingreso": "2018-01-01",
            "fecha_cierre": "2019-07-01",
            "evento": "desistido_o_abandonado",
            "seco_nombre": "Minería",  # mining → should trigger
        },
    ], date_cols=["fecha_ingreso", "fecha_cierre"])

    df_no_mining = _make_df([{
        "exp_id": "NEW_NO",
        "titular_nombre": "Empresa M",
        "fecha_ingreso": "2020-01-01",
    }], date_cols=["fecha_ingreso"])

    # Remove the mining row to test non-mining only case
    sea_no_mining = sea[sea["seco_nombre"] == "Energía"].copy()
    result = add_titular_features(df_no_mining, sea_no_mining)
    assert result.iloc[0]["reingreso_probable"] == 0, (
        "Non-mining closure must not set reingreso_probable"
    )

    # With mining closure present → should be 1
    result_with_mining = add_titular_features(df_no_mining, sea)
    assert result_with_mining.iloc[0]["reingreso_probable"] == 1, (
        "Mining closure within 365 days must set reingreso_probable=1"
    )


# ── Robustness: seco_nombre required ─────────────────────────────────────────

def test_add_titular_features_missing_seco_nombre_raises():
    """add_titular_features raises ValueError when seco_nombre column is absent."""
    from cmip.ml.features import add_titular_features

    sea = _make_df([{
        "exp_id": "S1",
        "titular_nombre": "Empresa X",
        "fecha_ingreso": "2015-01-01",
        "fecha_cierre": None,
        "evento": None,
        # deliberately no seco_nombre
    }], date_cols=["fecha_ingreso", "fecha_cierre"])

    df = _make_df([{
        "exp_id": "N1",
        "titular_nombre": "Empresa X",
        "fecha_ingreso": "2018-01-01",
    }], date_cols=["fecha_ingreso"])

    with pytest.raises(ValueError, match="seco_nombre"):
        add_titular_features(df, sea)
