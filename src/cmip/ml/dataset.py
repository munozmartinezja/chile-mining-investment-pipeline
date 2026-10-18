"""ML dataset: eligible population with binary 24-month approval target."""
from __future__ import annotations

import pandas as pd

from cmip.config import SEA_DATA_CURRENCY_DATE
from cmip.survival import DAYS_PER_MONTH, POPULATION_PATH

HORIZON_DAYS: float = 24 * DAYS_PER_MONTH
HORIZON_TD: pd.Timedelta = pd.to_timedelta(HORIZON_DAYS, unit="D")

_PRIVATE_OUTPUT_COLUMNS = frozenset(
    {"titular_nombre", "empresa_nombre", "exp_nombre"}
)

_OUTPUT_COLUMNS = frozenset({"exp_id", "fecha_ingreso", "y"})


def _assert_no_private_columns(frame: pd.DataFrame, context: str = "") -> None:
    leaked = _PRIVATE_OUTPUT_COLUMNS.intersection(frame.columns)
    if leaked:
        raise ValueError(
            f"Refusing to output private columns{' in ' + context if context else ''}: "
            f"{sorted(leaked)}"
        )


def build_ml_population(
    population: pd.DataFrame,
    sea_projects: pd.DataFrame | None = None,
) -> pd.DataFrame:
    """Return eligible rows with binary target y and intake-day features.

    Output columns are exactly: exp_id, fecha_ingreso, y, and ALL_FEATURES.
    No leakage or private columns are included.
    """
    from cmip.ml.features import ALL_FEATURES, add_features

    cutoff = pd.Timestamp(SEA_DATA_CURRENCY_DATE)

    eligible = population.loc[
        population["fecha_ingreso"] + HORIZON_TD <= cutoff
    ].copy()

    eligible["y"] = (
        (eligible["evento"] == "aprobado") & (eligible["duration_days"] <= HORIZON_DAYS)
    ).astype(int)

    eligible["anio_ingreso"] = eligible["fecha_ingreso"].dt.year

    result = add_features(eligible, sea_projects=sea_projects)

    missing_feats = [f for f in ALL_FEATURES if f not in result.columns]
    if missing_feats:
        raise ValueError(
            f"build_ml_population: missing features after add_features: {sorted(missing_feats)}"
        )

    # Drop private columns used internally during feature engineering
    result = result.drop(
        columns=[c for c in _PRIVATE_OUTPUT_COLUMNS if c in result.columns]
    )
    _assert_no_private_columns(result, "build_ml_population output")

    # Restrict to output schema: exp_id, fecha_ingreso, y + ALL_FEATURES
    keep_cols = ["exp_id", "fecha_ingreso", "y"] + ALL_FEATURES
    result = result[[c for c in keep_cols if c in result.columns]].copy()

    return result


def load_ml_population() -> pd.DataFrame:
    """Load survival population from default path and build ML dataset."""
    population = pd.read_parquet(POPULATION_PATH)
    return build_ml_population(population)
