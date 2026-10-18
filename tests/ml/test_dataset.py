"""Tests 1, 2, 6(A6), 11, A2: target variable, eligibility, column schema, integration."""
from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

ROOT = Path(__file__).parent.parent.parent

_SURVIVAL_POPULATION = ROOT / "data/processed/survival_population.parquet"

requires_local_data = pytest.mark.skipif(
    not _SURVIVAL_POPULATION.exists(),
    reason="requires data/processed/survival_population.parquet",
)


def _make_population(rows: list[dict]) -> pd.DataFrame:
    df = pd.DataFrame(rows)
    df["fecha_ingreso"] = pd.to_datetime(df["fecha_ingreso"])
    if "fecha_cierre" in df.columns:
        df["fecha_cierre"] = pd.to_datetime(df["fecha_cierre"])
    return df


def _build_ml_population_synthetic(population: pd.DataFrame) -> pd.DataFrame:
    from cmip.ml.dataset import build_ml_population

    sea = population[
        ["exp_id", "titular_nombre", "fecha_ingreso", "fecha_cierre", "evento"]
    ].copy()
    sea["instrumento"] = population.get(
        "instrumento", pd.Series(["DIA"] * len(population))
    )
    sea["region"] = population.get(
        "region", pd.Series(["Atacama"] * len(population))
    )
    sea["tipologia"] = population.get(
        "tipologia", pd.Series(["Proyecto"] * len(population))
    )
    sea["inversion_musd"] = population.get(
        "inversion_musd", pd.Series([100.0] * len(population))
    )
    sea["seco_nombre"] = "Minería"

    return build_ml_population(population, sea_projects=sea)


# ── Test 1: target variable edge cases ────────────────────────────────────────

def test_y_approved_exactly_at_horizon():
    """Approved on day HORIZON_DAYS → y = 1."""
    from cmip.config import SEA_DATA_CURRENCY_DATE
    from cmip.ml.dataset import HORIZON_DAYS, HORIZON_TD

    cutoff = pd.Timestamp(SEA_DATA_CURRENCY_DATE)
    ingreso = cutoff - HORIZON_TD - pd.to_timedelta(1, unit="D")
    rows = [{
        "exp_id": "A1",
        "fecha_ingreso": ingreso,
        "fecha_cierre": ingreso + HORIZON_TD,
        "evento": "aprobado",
        "duration_days": HORIZON_DAYS,
        "instrumento": "DIA",
        "tipologia": "Proyecto",
        "region": "Atacama",
        "macro_zona": "Norte",
        "titular_nombre": "Empresa A",
        "inversion_musd": 200.0,
    }]
    pop = _make_population(rows)
    result = _build_ml_population_synthetic(pop)
    assert len(result) == 1
    assert result.iloc[0]["y"] == 1


def test_y_approved_one_day_after_horizon():
    """Approved one day after HORIZON_DAYS → y = 0."""
    from cmip.config import SEA_DATA_CURRENCY_DATE
    from cmip.ml.dataset import HORIZON_DAYS, HORIZON_TD

    cutoff = pd.Timestamp(SEA_DATA_CURRENCY_DATE)
    ingreso = cutoff - HORIZON_TD - pd.to_timedelta(2, unit="D")
    rows = [{
        "exp_id": "A2",
        "fecha_ingreso": ingreso,
        "fecha_cierre": ingreso + HORIZON_TD + pd.to_timedelta(1, unit="D"),
        "evento": "aprobado",
        "duration_days": HORIZON_DAYS + 1,
        "instrumento": "DIA",
        "tipologia": "Proyecto",
        "region": "Atacama",
        "macro_zona": "Norte",
        "titular_nombre": "Empresa A",
        "inversion_musd": 200.0,
    }]
    pop = _make_population(rows)
    result = _build_ml_population_synthetic(pop)
    assert len(result) == 1
    assert result.iloc[0]["y"] == 0


def test_y_desistido_is_zero():
    """Desistido early → y = 0."""
    from cmip.config import SEA_DATA_CURRENCY_DATE
    from cmip.ml.dataset import HORIZON_TD

    cutoff = pd.Timestamp(SEA_DATA_CURRENCY_DATE)
    ingreso = cutoff - HORIZON_TD - pd.to_timedelta(5, unit="D")
    rows = [{
        "exp_id": "A3",
        "fecha_ingreso": ingreso,
        "fecha_cierre": ingreso + pd.to_timedelta(100, unit="D"),
        "evento": "desistido_o_abandonado",
        "duration_days": 100.0,
        "instrumento": "EIA",
        "tipologia": "Proyecto",
        "region": "Antofagasta",
        "macro_zona": "Norte",
        "titular_nombre": "Empresa B",
        "inversion_musd": 500.0,
    }]
    pop = _make_population(rows)
    result = _build_ml_population_synthetic(pop)
    assert len(result) == 1
    assert result.iloc[0]["y"] == 0


def test_y_en_tramite_complete_horizon_is_zero():
    """A6: en_tramite with complete horizon → y = 0."""
    from cmip.config import SEA_DATA_CURRENCY_DATE
    from cmip.ml.dataset import HORIZON_DAYS, HORIZON_TD

    cutoff = pd.Timestamp(SEA_DATA_CURRENCY_DATE)
    ingreso = cutoff - HORIZON_TD - pd.to_timedelta(10, unit="D")
    rows = [{
        "exp_id": "A6",
        "fecha_ingreso": ingreso,
        "fecha_cierre": None,
        "evento": "en_tramite",
        "duration_days": HORIZON_DAYS + 10,
        "instrumento": "DIA",
        "tipologia": "Proyecto",
        "region": "Atacama",
        "macro_zona": "Norte",
        "titular_nombre": "Empresa F",
        "inversion_musd": 300.0,
    }]
    pop = _make_population(rows)
    result = _build_ml_population_synthetic(pop)
    assert len(result) == 1
    assert result.iloc[0]["y"] == 0


# ── Test 2: eligibility — incomplete horizon excluded ─────────────────────────

def test_incomplete_horizon_excluded():
    """Case whose 24m window has not closed yet is excluded."""
    from cmip.config import SEA_DATA_CURRENCY_DATE
    from cmip.ml.dataset import HORIZON_TD

    cutoff = pd.Timestamp(SEA_DATA_CURRENCY_DATE)
    ingreso_excluded = cutoff - HORIZON_TD + pd.to_timedelta(10, unit="D")
    ingreso_included = cutoff - HORIZON_TD - pd.to_timedelta(10, unit="D")

    rows = [
        {
            "exp_id": "E1",
            "fecha_ingreso": ingreso_included,
            "fecha_cierre": None,
            "evento": "en_tramite",
            "duration_days": (cutoff - ingreso_included).days,
            "instrumento": "DIA",
            "tipologia": "Proyecto",
            "region": "Atacama",
            "macro_zona": "Norte",
            "titular_nombre": "Empresa C",
            "inversion_musd": 50.0,
        },
        {
            "exp_id": "E2",
            "fecha_ingreso": ingreso_excluded,
            "fecha_cierre": None,
            "evento": "en_tramite",
            "duration_days": (cutoff - ingreso_excluded).days,
            "instrumento": "DIA",
            "tipologia": "Proyecto",
            "region": "Atacama",
            "macro_zona": "Norte",
            "titular_nombre": "Empresa D",
            "inversion_musd": 50.0,
        },
    ]
    pop = _make_population(rows)
    result = _build_ml_population_synthetic(pop)
    assert "E2" not in result["exp_id"].values
    assert "E1" in result["exp_id"].values


# ── A2: column schema ─────────────────────────────────────────────────────────

def test_build_ml_population_column_schema():
    """A2: output columns are exactly exp_id, fecha_ingreso, y, and ALL_FEATURES."""
    from cmip.config import SEA_DATA_CURRENCY_DATE
    from cmip.ml.dataset import HORIZON_TD
    from cmip.ml.features import ALL_FEATURES

    cutoff = pd.Timestamp(SEA_DATA_CURRENCY_DATE)
    ingreso = cutoff - HORIZON_TD - pd.to_timedelta(10, unit="D")
    rows = [{
        "exp_id": "C1",
        "fecha_ingreso": ingreso,
        "fecha_cierre": ingreso + pd.to_timedelta(400, unit="D"),
        "evento": "aprobado",
        "duration_days": 400.0,
        "instrumento": "DIA",
        "tipologia": "Proyecto",
        "region": "Atacama",
        "macro_zona": "Norte",
        "titular_nombre": "Empresa C",
        "inversion_musd": 100.0,
    }]
    pop = _make_population(rows)
    result = _build_ml_population_synthetic(pop)

    expected_cols = {"exp_id", "fecha_ingreso", "y"} | set(ALL_FEATURES)
    assert set(result.columns) == expected_cols, (
        f"Extra: {set(result.columns) - expected_cols}, "
        f"Missing: {expected_cols - set(result.columns)}"
    )


# ── Robustness: missing features after add_features ──────────────────────────

def test_build_ml_population_raises_on_missing_features(monkeypatch):
    """build_ml_population raises ValueError when add_features drops a feature."""
    import cmip.ml.features as feat_mod
    from cmip.config import SEA_DATA_CURRENCY_DATE
    from cmip.ml.dataset import HORIZON_TD, build_ml_population
    from cmip.ml.features import ALL_FEATURES
    from cmip.ml.features import add_features as real_add_features

    def _broken_add_features(df, sea_projects=None):
        result = real_add_features(df, sea_projects=sea_projects)
        return result.drop(columns=[ALL_FEATURES[0]])

    monkeypatch.setattr(feat_mod, "add_features", _broken_add_features)

    cutoff = pd.Timestamp(SEA_DATA_CURRENCY_DATE)
    ingreso = cutoff - HORIZON_TD - pd.to_timedelta(10, unit="D")
    pop = _make_population([{
        "exp_id": "X1",
        "fecha_ingreso": ingreso,
        "fecha_cierre": ingreso + pd.to_timedelta(400, unit="D"),
        "evento": "aprobado",
        "duration_days": 400.0,
        "instrumento": "DIA",
        "tipologia": "Proyecto",
        "region": "Atacama",
        "macro_zona": "Norte",
        "titular_nombre": "Empresa X",
        "inversion_musd": 100.0,
    }])
    sea = pop[["exp_id", "titular_nombre", "fecha_ingreso", "fecha_cierre", "evento"]].copy()
    sea["instrumento"] = "DIA"
    sea["region"] = "Atacama"
    sea["tipologia"] = "Proyecto"
    sea["inversion_musd"] = 100.0
    sea["seco_nombre"] = "Minería"

    with pytest.raises(ValueError, match="missing features"):
        build_ml_population(pop, sea_projects=sea)


# ── Test 11: integration with actual data ─────────────────────────────────────

@requires_local_data
def test_ml_population_integration():
    """Integration: y is binary, no dup exp_id, size < 995, correct column schema."""
    from cmip.ml.dataset import load_ml_population
    from cmip.ml.features import ALL_FEATURES

    dataset = load_ml_population()
    assert set(dataset["y"].unique()).issubset({0, 1})
    assert dataset["exp_id"].nunique() == len(dataset)
    assert len(dataset) < 995

    expected_cols = {"exp_id", "fecha_ingreso", "y"} | set(ALL_FEATURES)
    assert set(dataset.columns) == expected_cols
