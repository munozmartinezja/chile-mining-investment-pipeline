from __future__ import annotations

import pandas as pd

from cmip.config import PROJECT_ROOT, SEA_DATA_CURRENCY_DATE


def test_sea_data_currency_date_equals_latest_observed_extract_date() -> None:
    """Catch censoring open cases after the extract's last observed record."""
    sea = pd.read_parquet(PROJECT_ROOT / "data/interim/sea_mining.parquet")
    observed = pd.concat(
        [
            pd.to_datetime(sea[column], errors="coerce")
            for column in ("fecha_ingreso", "fecha_cierre", "exp_fecha_rca")
        ]
    ).max()

    assert observed.date().isoformat() == "2026-08-25"
    assert observed.date() == SEA_DATA_CURRENCY_DATE
