"""OOF evaluation, metrics, bootstrap CIs, calibration, and ablation."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import numpy as np
import pandas as pd
from sklearn.metrics import (
    brier_score_loss,
    log_loss,
    precision_recall_curve,
    roc_auc_score,
)

from cmip.ml.features import (
    NUMERIC_FEATURES,
    split_xy,
)
from cmip.ml.models import (
    baseline_predict,
    extract_logit_coefs,
    fit_hgb,
    fit_logistic,
    fit_m2c,
)
from cmip.ml.split import SplitResult

BOOTSTRAP_N = 1_000
BOOTSTRAP_SEED = 42
EIA_MIN_N = 30
EIA_MIN_CLASS = 5

_RARE_CATS = ["tipologia", "region"]
_PLAIN_CATS = ["instrumento", "macro_zona"]

ABLATION_BLOCKS: dict[str, list[str]] = {
    "titular": [
        "titular_n_previos",
        "titular_aprob_previas",
        "titular_cierres_neg_previos",
        "reingreso_probable",
    ],
    "carga": ["carga_sea_region"],
    "calendario": ["mes_sin", "mes_cos"],
}


def _pr_auc(y_true: np.ndarray, y_score: np.ndarray) -> float:
    precision, recall, _ = precision_recall_curve(y_true, y_score)
    return float(np.trapezoid(precision[::-1], recall[::-1]))


def _metrics_for(
    y_true: np.ndarray, y_score: np.ndarray, b0_score: np.ndarray
) -> dict[str, Any]:
    n = len(y_true)
    pos = int(y_true.sum())
    if len(np.unique(y_true)) < 2:
        return {
            "n": n,
            "positivos": pos,
            "roc_auc": float("nan"),
            "pr_auc": float("nan"),
            "brier": float("nan"),
            "brier_skill": float("nan"),
            "log_loss": float("nan"),
        }

    brier = brier_score_loss(y_true, y_score)
    brier_b0 = brier_score_loss(y_true, b0_score)
    brier_skill = 1.0 - brier / brier_b0 if brier_b0 > 0 else float("nan")
    return {
        "n": n,
        "positivos": pos,
        "roc_auc": roc_auc_score(y_true, y_score),
        "pr_auc": _pr_auc(y_true, y_score),
        "brier": brier,
        "brier_skill": brier_skill,
        "log_loss": log_loss(y_true, y_score),
    }


@dataclass
class OofResult:
    predictions: pd.DataFrame
    metrics_by_fold: pd.DataFrame
    metrics_agg: dict[str, Any]
    bootstrap_ci: dict[str, Any]
    calibration: pd.DataFrame
    logit_coefs: pd.DataFrame
    eia_metrics: dict[str, Any]
    ablation: pd.DataFrame
    skipped: list[dict[str, Any]] = field(default_factory=list)


def _bootstrap_roc_auc(
    y_true: np.ndarray,
    y_score: np.ndarray,
    n: int = BOOTSTRAP_N,
    seed: int = BOOTSTRAP_SEED,
) -> tuple[float, float]:
    rng = np.random.default_rng(seed)
    aucs = []
    for _ in range(n):
        idx = rng.integers(0, len(y_true), size=len(y_true))
        yt, ys = y_true[idx], y_score[idx]
        if len(np.unique(yt)) < 2:
            continue
        aucs.append(roc_auc_score(yt, ys))
    aucs_arr = np.array(aucs)
    return float(np.percentile(aucs_arr, 2.5)), float(np.percentile(aucs_arr, 97.5))


def _calibration_table(
    y_true: np.ndarray, y_score: np.ndarray, model: str, n_bins: int = 10
) -> pd.DataFrame:
    quantiles = np.percentile(y_score, np.linspace(0, 100, n_bins + 1))
    quantiles = np.unique(quantiles)
    bin_ids = np.digitize(y_score, quantiles[1:-1])
    rows = []
    for b in range(len(quantiles) - 1):
        mask = bin_ids == b
        if mask.sum() == 0:
            continue
        rows.append({
            "model": model,
            "bin": b,
            "mean_predicted": float(y_score[mask].mean()),
            "mean_observed": float(y_true[mask].mean()),
            "n": int(mask.sum()),
        })
    return pd.DataFrame(rows)


def _eia_metrics_for_model(
    oof: pd.DataFrame,
    pred_col: str,
) -> dict[str, Any]:
    eia_mask = oof["instrumento"] == "EIA"
    eia_y = oof.loc[eia_mask, "y"].to_numpy()
    eia_pred = oof.loc[eia_mask, pred_col].to_numpy()
    eia_b0 = oof.loc[eia_mask, "pred_b0"].to_numpy()
    n_eia = int(eia_mask.sum())
    n_eia_pos = int(eia_y.sum())
    n_eia_neg = n_eia - n_eia_pos
    if n_eia < EIA_MIN_N or n_eia_pos < EIA_MIN_CLASS or n_eia_neg < EIA_MIN_CLASS:
        return {
            "resultado": "insuficiente",
            "motivo": (
                f"n={n_eia} (mínimo {EIA_MIN_N}), "
                f"positivos={n_eia_pos}, negativos={n_eia_neg} "
                f"(mínimo {EIA_MIN_CLASS} de cada clase)"
            ),
        }
    return _metrics_for(eia_y, eia_pred, eia_b0)


def _run_ablation(
    dataset: pd.DataFrame,
    split: SplitResult,
    baseline_auc: dict[str, float],
) -> pd.DataFrame:
    """Run ablation study: remove one feature block at a time from M1 and M2."""
    rows = []

    for block_name, drop_cols in ABLATION_BLOCKS.items():
        num_feats = [f for f in NUMERIC_FEATURES if f not in drop_cols]
        rare_cats = [c for c in _RARE_CATS if c not in drop_cols]
        plain_cats = [c for c in _PLAIN_CATS if c not in drop_cols]
        keep_feats = num_feats + rare_cats + plain_cats

        for model_name, fit_fn in [("M1", fit_logistic), ("M2", fit_hgb)]:
            all_preds = []
            all_y = []

            for fold in split.folds:
                X_train = fold.train[keep_feats].copy()
                y_train = fold.train["y"]
                X_test = fold.test[keep_feats].copy()
                y_test = fold.test["y"]

                pipe = fit_fn(
                    X_train, y_train,
                    numeric_features=num_feats,
                    rare_cats=rare_cats or None,
                    plain_cats=plain_cats or None,
                )
                preds = pipe.predict_proba(X_test)[:, 1]
                all_preds.extend(preds.tolist())
                all_y.extend(y_test.tolist())

            y_arr = np.array(all_y)
            p_arr = np.array(all_preds)

            auc = (
                float("nan") if len(np.unique(y_arr)) < 2
                else float(roc_auc_score(y_arr, p_arr))
            )

            delta = auc - baseline_auc.get(model_name, float("nan"))
            rows.append({
                "bloque_quitado": block_name,
                "modelo": model_name,
                "roc_auc_oof": auc,
                "delta_vs_completo": delta,
            })

    return pd.DataFrame(rows)


def run_oof(
    dataset: pd.DataFrame,
    split: SplitResult,
) -> OofResult:
    """Run OOF evaluation for B0, M1 (logistic), M2 (HGB), M2c (calibrated HGB)."""
    all_records: list[pd.DataFrame] = []
    fold_rows: list[dict[str, Any]] = []

    for fold in split.folds:
        X_train, y_train = split_xy(fold.train)
        X_test, y_test = split_xy(fold.test)

        b0 = baseline_predict(fold.train, fold.test)
        m1_pipe = fit_logistic(X_train, y_train)
        m2_pipe = fit_hgb(X_train, y_train)
        m2c_pipe = fit_m2c(X_train, y_train)

        m1_pred = m1_pipe.predict_proba(X_test)[:, 1]
        m2_pred = m2_pipe.predict_proba(X_test)[:, 1]
        m2c_pred = m2c_pipe.predict_proba(X_test)[:, 1]

        rec = fold.test[["exp_id", "instrumento", "y"]].copy()
        rec["fold_year"] = fold.year
        rec["pred_b0"] = b0
        rec["pred_m1"] = m1_pred
        rec["pred_m2"] = m2_pred
        rec["pred_m2c"] = m2c_pred
        all_records.append(rec)

        y_np = y_test.to_numpy()
        fold_rows.append({"fold_year": fold.year, "model": "B0",
                          **_metrics_for(y_np, b0, b0)})
        fold_rows.append({"fold_year": fold.year, "model": "M1",
                          **_metrics_for(y_np, m1_pred, b0)})
        fold_rows.append({"fold_year": fold.year, "model": "M2",
                          **_metrics_for(y_np, m2_pred, b0)})
        fold_rows.append({"fold_year": fold.year, "model": "M2c",
                          **_metrics_for(y_np, m2c_pred, b0)})

    if not all_records:
        raise RuntimeError("No folds produced predictions — all folds were skipped.")

    oof = pd.concat(all_records, ignore_index=True)
    y_all = oof["y"].to_numpy()

    agg: dict[str, Any] = {}
    ci: dict[str, Any] = {}
    metrics_by_fold = pd.DataFrame(fold_rows)

    models_cols = [
        ("B0", "pred_b0"),
        ("M1", "pred_m1"),
        ("M2", "pred_m2"),
        ("M2c", "pred_m2c"),
    ]

    for model, col in models_cols:
        preds = oof[col].to_numpy()
        b0_preds = oof["pred_b0"].to_numpy()
        agg[model] = _metrics_for(y_all, preds, b0_preds)

        # E2: fold-level AUC stats
        fold_aucs = (
            metrics_by_fold[metrics_by_fold["model"] == model]["roc_auc"]
            .dropna()
            .values
        )
        agg[model]["roc_auc_media_folds"] = (
            float(np.mean(fold_aucs)) if len(fold_aucs) > 0 else float("nan")
        )
        agg[model]["roc_auc_min_fold"] = (
            float(np.min(fold_aucs)) if len(fold_aucs) > 0 else float("nan")
        )

        lo, hi = _bootstrap_roc_auc(y_all, preds)
        ci[f"{model}_roc_auc_ci_lo"] = lo
        ci[f"{model}_roc_auc_ci_hi"] = hi

    for model_a, model_b in [("M2", "B0"), ("M1", "B0"), ("M2c", "B0")]:
        col_a = f"pred_{model_a.lower()}"
        col_b = f"pred_{model_b.lower()}"
        rng = np.random.default_rng(BOOTSTRAP_SEED)
        diffs = []
        for _ in range(BOOTSTRAP_N):
            idx = rng.integers(0, len(y_all), size=len(y_all))
            yt = y_all[idx]
            if len(np.unique(yt)) < 2:
                continue
            da = roc_auc_score(yt, oof[col_a].to_numpy()[idx])
            db = roc_auc_score(yt, oof[col_b].to_numpy()[idx])
            diffs.append(da - db)
        diffs_arr = np.array(diffs)
        key = f"{model_a}_minus_{model_b}"
        ci[f"{key}_ci_lo"] = float(np.percentile(diffs_arr, 2.5))
        ci[f"{key}_ci_hi"] = float(np.percentile(diffs_arr, 97.5))

    # E1: calibration tables for M1, M2, M2c
    cal_frames = []
    for m, col in [("M1", "pred_m1"), ("M2", "pred_m2"), ("M2c", "pred_m2c")]:
        cal_frames.append(_calibration_table(y_all, oof[col].to_numpy(), model=m))
    calibration = pd.concat(cal_frames, ignore_index=True)

    # E4: EIA metrics for M1, M2, M2c
    eia_metrics: dict[str, Any] = {}
    for m, col in [("M1", "pred_m1"), ("M2", "pred_m2"), ("M2c", "pred_m2c")]:
        eia_metrics[m] = _eia_metrics_for_model(oof, col)

    # Descriptive logistic fit on all eligible data
    X_all, y_all_series = split_xy(dataset)
    logit_pipeline_all = fit_logistic(X_all, y_all_series)
    logit_coefs = extract_logit_coefs(logit_pipeline_all)

    # E3: ablation
    baseline_auc_map = {
        m: agg[m]["roc_auc"] for m in ["M1", "M2"]
    }
    ablation = _run_ablation(dataset, split, baseline_auc_map)

    skipped_info = [{"year": s.year, "reason": s.reason} for s in split.skipped]

    return OofResult(
        predictions=oof,
        metrics_by_fold=metrics_by_fold,
        metrics_agg=agg,
        bootstrap_ci=ci,
        calibration=calibration,
        logit_coefs=logit_coefs,
        eia_metrics=eia_metrics,
        ablation=ablation,
        skipped=skipped_info,
    )
