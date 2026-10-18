"""Tests 7, 9: rare category encoding in test, reproducibility."""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

sklearn = pytest.importorskip("sklearn")


def _make_xy(n: int = 200, seed: int = 0) -> tuple[pd.DataFrame, pd.Series]:
    rng = np.random.default_rng(seed)
    regions = ["Atacama", "Antofagasta", "Tarapacá", "Coquimbo", "Norte Chico"]
    tipologias = ["Tipo_A", "Tipo_B", "Tipo_C", "Tipo_D", "Tipo_E"]

    df = pd.DataFrame({
        "log_inversion": rng.uniform(2, 8, n),
        "inversion_faltante": rng.integers(0, 2, n),
        "anio_ingreso": rng.integers(2010, 2023, n),
        "mes_sin": np.sin(2 * np.pi * rng.integers(1, 13, n) / 12),
        "mes_cos": np.cos(2 * np.pi * rng.integers(1, 13, n) / 12),
        "titular_n_previos": rng.integers(0, 5, n),
        "titular_aprob_previas": rng.integers(0, 3, n),
        "titular_cierres_neg_previos": rng.integers(0, 2, n),
        "reingreso_probable": rng.integers(0, 2, n),
        "carga_sea_region": rng.integers(0, 30, n),
        "instrumento": rng.choice(["DIA", "EIA"], n),
        "tipologia": rng.choice(tipologias, n),
        "macro_zona": rng.choice(["Norte", "Centro", "Sur"], n),
        "region": rng.choice(regions, n),
    })
    y = pd.Series(rng.integers(0, 2, n), name="y")
    return df, y


# ── Test 7: rare category in test set handled without error ───────────────────

def test_rare_category_in_test_no_error():
    """A category that appears only in test is silently encoded as 'otra'."""
    from cmip.ml.models import fit_logistic

    X_train, y_train = _make_xy(n=200)
    X_test, _ = _make_xy(n=20, seed=99)

    X_test = X_test.copy()
    X_test.iloc[0, X_test.columns.get_loc("tipologia")] = "UNSEEN_TYPE_ZZZZ"

    pipe = fit_logistic(X_train, y_train)
    proba = pipe.predict_proba(X_test)[:, 1]
    assert len(proba) == len(X_test)
    assert np.all(np.isfinite(proba))


# ── Test 9: reproducibility ───────────────────────────────────────────────────

def test_reproducibility():
    """Two runs on identical data produce byte-identical OOF predictions."""
    import datetime

    from cmip.ml.evaluate import run_oof
    from cmip.ml.split import temporal_split

    rng2 = np.random.default_rng(42)
    rows = []
    for year in range(2010, 2025):
        n_y = 40
        for i in range(n_y):
            rows.append({
                "exp_id": f"E{len(rows):04d}",
                "fecha_ingreso": pd.Timestamp(datetime.date(year, (i % 12) + 1, 1)),
                "instrumento": "DIA" if i % 3 else "EIA",
                "tipologia": "Tipo_A",
                "macro_zona": "Norte",
                "region": "Atacama",
                "y": int(rng2.integers(0, 2)),
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
            })

    X = pd.DataFrame(rows)
    X["fecha_ingreso"] = pd.to_datetime(X["fecha_ingreso"])

    split1 = temporal_split(X)
    split2 = temporal_split(X)

    oof1 = run_oof(X, split1)
    oof2 = run_oof(X, split2)

    pd.testing.assert_frame_equal(
        oof1.predictions.sort_values("exp_id").reset_index(drop=True),
        oof2.predictions.sort_values("exp_id").reset_index(drop=True),
    )
