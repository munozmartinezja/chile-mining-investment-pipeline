"""Intake-day features for the 24-month approval ML model."""
from __future__ import annotations

import math
import unicodedata
from pathlib import Path

import numpy as np
import pandas as pd

from cmip.config import INTERIM_DIR
from cmip.survival import _macro_zone

SEA_PROJECTS_PATH: Path = INTERIM_DIR / "sea_projects.parquet"

LEAKAGE_COLUMNS = frozenset(
    {
        "fecha_cierre",
        "duration_days",
        "duracion_dias",
        "evento",
        "estado",
        "estado_post_rca",
        "eval_habil",
        "sus_habil",
        "sussea_habil",
        "dias_corridos",
        "exp_fecha_rca",
        "exp_nro_rca",
        "approval_event",
        "competing_event",
        "exp_id",
        "exp_nombre",
        "titular_nombre",
        "empresa_nombre",
        "y",
    }
)

_NEGATIVE_EVENTOS = frozenset(
    {"desistido_o_abandonado", "rechazado", "termino_anticipado"}
)

NUMERIC_FEATURES = [
    "log_inversion",
    "inversion_faltante",
    "anio_ingreso",
    "mes_sin",
    "mes_cos",
    "titular_n_previos",
    "titular_aprob_previas",
    "titular_cierres_neg_previos",
    "reingreso_probable",
    "carga_sea_region",
]

CATEGORICAL_FEATURES = ["instrumento", "tipologia", "macro_zona", "region"]

ALL_FEATURES = NUMERIC_FEATURES + CATEGORICAL_FEATURES


def _normalize_name(name: object) -> str | None:
    """Casefold, remove diacritics, collapse whitespace. Returns None for null/empty."""
    if name is None or (isinstance(name, float) and math.isnan(name)):
        return None
    text = str(name).strip()
    if not text:
        return None
    nfkd = unicodedata.normalize("NFKD", text)
    ascii_only = "".join(c for c in nfkd if not unicodedata.combining(c))
    return " ".join(ascii_only.casefold().split()) or None


def add_cyclic_month(df: pd.DataFrame) -> pd.DataFrame:
    """Add mes_sin and mes_cos columns from fecha_ingreso month."""
    month = df["fecha_ingreso"].dt.month
    df = df.copy()
    df["mes_sin"] = np.sin(2 * math.pi * month / 12)
    df["mes_cos"] = np.cos(2 * math.pi * month / 12)
    return df


def add_log_inversion(df: pd.DataFrame) -> pd.DataFrame:
    """Add log_inversion (log1p) and inversion_faltante (1 when missing or ≤ 0)."""
    df = df.copy()
    inv = pd.to_numeric(df.get("inversion_musd"), errors="coerce")
    missing = inv.isna() | (inv <= 0)
    df["inversion_faltante"] = missing.astype(int)
    df["log_inversion"] = np.log1p(inv.where(~missing, 0.0))
    return df


def add_macro_zona(df: pd.DataFrame) -> pd.DataFrame:
    """Add macro_zona from region using the survival module mapping."""
    df = df.copy()
    df["macro_zona"] = df["region"].map(_macro_zone)
    return df


def add_titular_features(
    df: pd.DataFrame,
    sea_projects: pd.DataFrame,
) -> pd.DataFrame:
    """Add titular history features using strictly-prior information."""
    df = df.copy()

    cols = ["exp_id", "titular_nombre", "fecha_ingreso", "fecha_cierre", "evento"]
    sea = sea_projects[cols].copy()
    sea["_norm_titular"] = sea["titular_nombre"].map(_normalize_name)

    df["_norm_titular"] = df["titular_nombre"].map(_normalize_name)

    # A5: reingreso_probable must be mining-only
    mining_sea = sea
    if "seco_nombre" in sea_projects.columns:
        mining_sea = sea_projects[sea_projects["seco_nombre"] == "Minería"][cols].copy()
        mining_sea["_norm_titular"] = mining_sea["titular_nombre"].map(_normalize_name)

    n_previos = []
    aprob_prev = []
    cierres_neg_prev = []
    reingreso = []

    for _, row in df.iterrows():
        t = row["fecha_ingreso"]
        norm = row["_norm_titular"]

        # A4: null titular → all four features = 0
        if norm is None:
            n_previos.append(0)
            aprob_prev.append(0)
            cierres_neg_prev.append(0)
            reingreso.append(0)
            continue

        prior = sea.loc[sea["_norm_titular"] == norm]
        prior_strict = prior.loc[prior["fecha_ingreso"] < t]

        n_previos.append(len(prior_strict))

        prior_closed_before = prior_strict.loc[
            prior_strict["fecha_cierre"].notna() & (prior_strict["fecha_cierre"] < t)
        ]
        aprob_prev.append(int((prior_closed_before["evento"] == "aprobado").sum()))
        cierres_neg_prev.append(
            int(prior_closed_before["evento"].isin(_NEGATIVE_EVENTOS).sum())
        )

        # A5: use only mining projects for reingreso_probable
        window_start = t - pd.to_timedelta(365, unit="D")
        mining_neg_in_window = mining_sea.loc[
            (mining_sea["_norm_titular"] == norm)
            & mining_sea["fecha_cierre"].notna()
            & (mining_sea["fecha_cierre"] >= window_start)
            & (mining_sea["fecha_cierre"] < t)
            & mining_sea["evento"].isin(_NEGATIVE_EVENTOS)
        ]
        reingreso.append(1 if len(mining_neg_in_window) > 0 else 0)

    df["titular_n_previos"] = n_previos
    df["titular_aprob_previas"] = aprob_prev
    df["titular_cierres_neg_previos"] = cierres_neg_prev
    df["reingreso_probable"] = reingreso

    df = df.drop(columns=["_norm_titular"])
    return df


def add_carga_sea_region(
    df: pd.DataFrame,
    sea_projects: pd.DataFrame,
) -> pd.DataFrame:
    """Add carga_sea_region: open filings in the same region at intake date."""
    df = df.copy()
    sea = sea_projects[["exp_id", "region", "fecha_ingreso", "fecha_cierre"]].copy()

    carga = []
    for _, row in df.iterrows():
        t = row["fecha_ingreso"]
        reg = row["region"]

        in_region = sea.loc[sea["region"] == reg]
        open_at_t = in_region.loc[
            (in_region["fecha_ingreso"] < t)
            & (in_region["fecha_cierre"].isna() | (in_region["fecha_cierre"] > t))
        ]
        carga.append(len(open_at_t))

    df["carga_sea_region"] = carga
    return df


def build_feature_matrix(df: pd.DataFrame) -> pd.DataFrame:
    """Return feature columns only; raise if any leakage column is present."""
    present_leakage = LEAKAGE_COLUMNS.intersection(df.columns)
    if present_leakage:
        raise ValueError(
            f"Leakage columns found in feature matrix: {sorted(present_leakage)}"
        )
    return df[ALL_FEATURES].copy()


def split_xy(frame: pd.DataFrame) -> tuple[pd.DataFrame, pd.Series]:
    """Return (X, y) from a population frame; validates ALL_FEATURES against leakage."""
    X_raw = frame[ALL_FEATURES].copy()
    X = build_feature_matrix(X_raw)
    y = frame["y"].copy()
    return X, y


def add_features(
    df: pd.DataFrame,
    sea_projects: pd.DataFrame | None = None,
) -> pd.DataFrame:
    """Apply all intake-day feature engineering to df."""
    if sea_projects is None:
        if not SEA_PROJECTS_PATH.exists():
            raise FileNotFoundError(
                f"sea_projects not found at {SEA_PROJECTS_PATH}; run `make data` first"
            )
        sea_projects = pd.read_parquet(SEA_PROJECTS_PATH)

    df = add_log_inversion(df)
    df = add_macro_zona(df)
    df = add_cyclic_month(df)
    df = add_titular_features(df, sea_projects)
    df = add_carga_sea_region(df, sea_projects)

    return df
