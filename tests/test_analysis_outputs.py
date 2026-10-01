from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
PORTFOLIO_PATH = PROJECT_ROOT / "data" / "processed" / "cochilco_seia.parquet"
KM_SUMMARY_PATH = PROJECT_ROOT / "data" / "processed" / "survival_km_summary.parquet"


@pytest.mark.skipif(
    not PORTFOLIO_PATH.exists(),
    reason="requires `make analysis` with a completed local docs/match_review.csv",
)
def test_cochilco_seia_has_59_rows_and_valid_confirmed_ids() -> None:
    portfolio = pd.read_parquet(PORTFOLIO_PATH)

    assert len(portfolio) == 59
    matched = portfolio.loc[portfolio["exp_id_confirmado"].notna()]
    duplicate_rows = matched["exp_id_confirmado"].duplicated(keep=False)
    assert matched.loc[duplicate_rows, "nota_agregacion"].all()


@pytest.mark.skipif(
    not KM_SUMMARY_PATH.exists(),
    reason="requires `make analysis` with local SEA extracts",
)
def test_km_median_dia_is_below_eia() -> None:
    summary = pd.read_parquet(KM_SUMMARY_PATH).set_index("instrumento")

    assert summary.loc["DIA", "mediana_km_meses"] < summary.loc["EIA", "mediana_km_meses"]

