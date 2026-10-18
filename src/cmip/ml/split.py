"""Rolling-origin temporal split for ML validation."""
from __future__ import annotations

import datetime
from dataclasses import dataclass, field

import pandas as pd

from cmip.ml.dataset import HORIZON_DAYS, HORIZON_TD

TEST_YEARS: tuple[int, ...] = (2018, 2019, 2020, 2021, 2022, 2023, 2024)
MIN_TRAIN: int = 150


@dataclass
class Fold:
    year: int
    train: pd.DataFrame
    test: pd.DataFrame


@dataclass
class SkippedFold:
    year: int
    reason: str


@dataclass
class SplitResult:
    folds: list[Fold] = field(default_factory=list)
    skipped: list[SkippedFold] = field(default_factory=list)


def temporal_split(
    df: pd.DataFrame,
    test_years: tuple[int, ...] = TEST_YEARS,
    min_train: int = MIN_TRAIN,
    horizon_days: float = HORIZON_DAYS,
) -> SplitResult:
    """Rolling-origin split with embargo.

    For test year Y, training uses only cases whose 24-month outcome
    was fully observable before 1-Jan-Y (strict embargo).
    """
    result = SplitResult()
    # A7: use pre-built timedelta to avoid generic-unit DeprecationWarning
    if horizon_days == HORIZON_DAYS:
        horizon_td = HORIZON_TD
    else:
        horizon_td = pd.to_timedelta(horizon_days, unit="D")

    for year in test_years:
        cutoff = pd.Timestamp(datetime.date(year, 1, 1))

        train = df.loc[df["fecha_ingreso"] + horizon_td < cutoff].copy()
        test = df.loc[df["fecha_ingreso"].dt.year == year].copy()

        if len(train) < min_train:
            result.skipped.append(
                SkippedFold(year=year, reason=f"train n={len(train)} < {min_train}")
            )
            continue

        if train["y"].nunique() < 2:
            result.skipped.append(
                SkippedFold(year=year, reason="single class in training fold")
            )
            continue

        if len(test) == 0:
            result.skipped.append(
                SkippedFold(year=year, reason="no test observations for this year")
            )
            continue

        result.folds.append(Fold(year=year, train=train, test=test))

    return result
