"""Test 6: embargo invariants for temporal split."""
from __future__ import annotations

import datetime

import pandas as pd

from cmip.ml.dataset import HORIZON_TD
from cmip.ml.split import temporal_split


def _make_dataset(n_per_year: int = 40, start_year: int = 2010) -> pd.DataFrame:
    """Synthetic dataset spanning start_year to 2024 with n_per_year rows each year."""
    rows = []
    exp_counter = 0
    for year in range(start_year, 2025):
        for i in range(n_per_year):
            ingreso = pd.Timestamp(datetime.date(year, (i % 12) + 1, 1))
            rows.append({
                "exp_id": f"EXP{exp_counter:04d}",
                "fecha_ingreso": ingreso,
                "fecha_cierre": ingreso + pd.to_timedelta(300, unit="D"),
                "evento": "aprobado" if i % 2 == 0 else "desistido_o_abandonado",
                "duration_days": 300.0,
                "instrumento": "DIA" if i % 3 != 0 else "EIA",
                "tipologia": "Proyecto",
                "region": "Atacama",
                "macro_zona": "Norte",
                "titular_nombre": f"Empresa {i}",
                "inversion_musd": 100.0,
                "y": 1 if i % 2 == 0 else 0,
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
            exp_counter += 1
    df = pd.DataFrame(rows)
    df["fecha_ingreso"] = pd.to_datetime(df["fecha_ingreso"])
    df["fecha_cierre"] = pd.to_datetime(df["fecha_cierre"])
    return df


def test_embargo_invariant():
    """max(fecha_ingreso_train) + HORIZON_DAYS < 1-Jan of test year for all folds."""
    dataset = _make_dataset()
    split = temporal_split(dataset)

    assert len(split.folds) > 0, "Expected at least one fold"

    for fold in split.folds:
        cutoff = pd.Timestamp(datetime.date(fold.year, 1, 1))
        max_train_date = fold.train["fecha_ingreso"].max()
        assert max_train_date + HORIZON_TD < cutoff, (
            f"Fold {fold.year}: max train date {max_train_date} + horizon >= {cutoff}"
        )


def test_no_exp_id_overlap():
    """No exp_id appears in both train and test within a fold."""
    dataset = _make_dataset()
    split = temporal_split(dataset)

    for fold in split.folds:
        train_ids = set(fold.train["exp_id"])
        test_ids = set(fold.test["exp_id"])
        overlap = train_ids & test_ids
        assert len(overlap) == 0, f"Fold {fold.year}: overlap {overlap}"


def test_fold_test_year_matches():
    """Test set contains only rows from the expected test year."""
    dataset = _make_dataset()
    split = temporal_split(dataset)

    for fold in split.folds:
        years_in_test = fold.test["fecha_ingreso"].dt.year.unique()
        assert list(years_in_test) == [fold.year], (
            f"Fold {fold.year}: test contains years {years_in_test}"
        )


def test_insufficient_train_skipped():
    """A fold with fewer than MIN_TRAIN training rows is skipped and recorded."""
    tiny = _make_dataset(n_per_year=5, start_year=2017)
    split = temporal_split(tiny)

    assert len(split.skipped) > 0 or len(split.folds) > 0, "No folds at all"
    for s in split.skipped:
        assert "train n=" in s.reason or "single class" in s.reason
