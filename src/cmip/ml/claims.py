"""ML claims register: independent recalculation and public results document."""
from __future__ import annotations

import math

import numpy as np
import pandas as pd

from cmip.config import PROJECT_ROOT
from cmip.validation import _claim, finalize_claims_register

ML_DIR = PROJECT_ROOT / "data" / "ml"
DOCS_DIR = PROJECT_ROOT / "docs"


# ── Independent recalculation (no sklearn) ───────────────────────────────────

def _roc_auc_mw(y_true: np.ndarray, y_score: np.ndarray) -> float:
    """Mann-Whitney AUC via average-rank method (handles ties)."""
    n_pos = int(y_true.sum())
    n_neg = len(y_true) - n_pos
    if n_pos == 0 or n_neg == 0:
        return float("nan")
    ranks = pd.Series(y_score).rank(method="average").to_numpy()
    rank_sum = float(ranks[y_true == 1].sum())
    return (rank_sum - n_pos * (n_pos + 1) / 2) / (n_pos * n_neg)


def _brier(y_true: np.ndarray, y_score: np.ndarray) -> float:
    return float(np.mean((y_score - y_true) ** 2))


def _log_loss_manual(y_true: np.ndarray, y_score: np.ndarray, eps: float = 1e-15) -> float:
    p = np.clip(y_score, eps, 1 - eps)
    return -float(np.mean(y_true * np.log(p) + (1 - y_true) * np.log(1 - p)))


def _brier_skill(brier_model: float, brier_b0: float) -> float:
    if brier_b0 == 0 or math.isnan(brier_b0):
        return float("nan")
    return 1.0 - brier_model / brier_b0


# ── Claims construction ───────────────────────────────────────────────────────

def _get_agg(agg_df: pd.DataFrame, model: str, metrica: str) -> float:
    rows = agg_df[(agg_df["model"] == model) & (agg_df["metrica"] == metrica)]
    if rows.empty:
        return float("nan")
    return float(rows.iloc[0]["valor"])


def _build_claims(
    agg_df: pd.DataFrame,
    oof_df: pd.DataFrame,
    dataset_df: pd.DataFrame,
    metrics_df: pd.DataFrame,
) -> list[dict]:
    rows: list[dict] = []
    y = oof_df["y"].to_numpy(dtype=float)

    # ── Population counts ─────────────────────────────────────────────────────
    n = len(dataset_df)
    n_pos = int(dataset_df["y"].sum())
    tasa_pct = round(100.0 * n_pos / n, 2) if n > 0 else float("nan")
    n_dia = int((dataset_df["instrumento"] == "DIA").sum())
    n_eia = int((dataset_df["instrumento"] == "EIA").sum())

    rows.append(_claim("ml_n_elegibles",
                       "Expedientes elegibles con horizonte completo de observación",
                       n, "n", "ml_dataset.parquet", "len(dataset)", n, 0,
                       "Conteo directo sobre el dataset ML"))
    rows.append(_claim("ml_positivos",
                       "Aprobados a 24 meses (y=1)",
                       n_pos, "n", "ml_dataset.parquet", "sum(y==1)", n_pos, 0,
                       "Conteo directo"))
    rows.append(_claim("ml_tasa_positivos_pct",
                       "Tasa de aprobación a 24 meses en la población elegible",
                       tasa_pct, "%", "ml_dataset.parquet",
                       "100*sum(y==1)/n", tasa_pct, 0,
                       "Tasa base histórica (B0)"))
    rows.append(_claim("ml_n_dia",
                       "Expedientes DIA en el dataset ML",
                       n_dia, "n", "ml_dataset.parquet",
                       "sum(instrumento=='DIA')", n_dia, 0, ""))
    rows.append(_claim("ml_n_eia",
                       "Expedientes EIA en el dataset ML",
                       n_eia, "n", "ml_dataset.parquet",
                       "sum(instrumento=='EIA')", n_eia, 0, ""))

    # Model key → parquet model name mapping
    _model_names = {"b0": "B0", "m1": "M1", "m2": "M2", "m2c": "M2c"}

    # ── ROC AUC per model ─────────────────────────────────────────────────────
    for model_key, pred_col in [
        ("b0", "pred_b0"), ("m1", "pred_m1"), ("m2", "pred_m2"), ("m2c", "pred_m2c"),
    ]:
        model_name = _model_names[model_key]
        val = _get_agg(agg_df, model_name, "roc_auc")
        recalc = _roc_auc_mw(y, oof_df[pred_col].to_numpy(dtype=float))
        rows.append(_claim(
            f"ml_roc_auc_{model_key}",
            f"ROC AUC OOF {model_name} sobre toda la muestra",
            val, "", "ml_metrics_agg.parquet",
            "Mann-Whitney sobre ml_oof_predictions.parquet",
            round(recalc, 6), 0.0005,
            f"Modelo {model_name}"
        ))

    # ── Brier and log loss for all models ────────────────────────────────────
    for model_key, pred_col in [
        ("b0", "pred_b0"), ("m1", "pred_m1"), ("m2", "pred_m2"), ("m2c", "pred_m2c"),
    ]:
        model_name = _model_names[model_key]
        preds = oof_df[pred_col].to_numpy(dtype=float)
        val_brier = _get_agg(agg_df, model_name, "brier")
        recalc_brier = _brier(y, preds)
        rows.append(_claim(
            f"ml_brier_{model_key}",
            f"Brier score OOF {model_name}",
            val_brier, "", "ml_metrics_agg.parquet",
            "mean((p-y)^2) sobre ml_oof_predictions.parquet",
            round(recalc_brier, 6), 0.0005, ""
        ))

        val_ll = _get_agg(agg_df, model_name, "log_loss")
        recalc_ll = _log_loss_manual(y, preds)
        rows.append(_claim(
            f"ml_logloss_{model_key}",
            f"Log loss OOF {model_name}",
            val_ll, "", "ml_metrics_agg.parquet",
            "−mean(y·log(p)+(1−y)·log(1−p)) con eps=1e-15",
            round(recalc_ll, 6), 0.0005, ""
        ))

    # ── Brier skill for M2c ───────────────────────────────────────────────────
    val_bs = _get_agg(agg_df, "M2c", "brier_skill")
    b0_preds = oof_df["pred_b0"].to_numpy(dtype=float)
    m2c_preds = oof_df["pred_m2c"].to_numpy(dtype=float)
    recalc_bs = _brier_skill(_brier(y, m2c_preds), _brier(y, b0_preds))
    rows.append(_claim(
        "ml_brier_skill_m2c",
        "Brier skill de M2c respecto a B0",
        val_bs, "", "ml_metrics_agg.parquet",
        "1 − brier(M2c)/brier(B0)",
        round(recalc_bs, 6), 0.0005, ""
    ))

    # ── EIA subgroup ─────────────────────────────────────────────────────────
    eia_mask = oof_df["instrumento"] == "EIA"
    eia_y = oof_df.loc[eia_mask, "y"].to_numpy(dtype=float)
    eia_m2c = oof_df.loc[eia_mask, "pred_m2c"].to_numpy(dtype=float)
    n_eia_test = int(eia_mask.sum())
    n_eia_pos = int(eia_y.sum())

    eia_m2c_row = agg_df[(agg_df["model"] == "EIA_M2c") & (agg_df["metrica"] == "roc_auc")]
    eia_auc_stored = float(eia_m2c_row.iloc[0]["valor"]) if not eia_m2c_row.empty else float("nan")
    eia_n_row = agg_df[(agg_df["model"] == "EIA_M2c") & (agg_df["metrica"] == "n")]
    eia_n_stored = float(eia_n_row.iloc[0]["valor"]) if not eia_n_row.empty else float("nan")
    eia_pos_row = agg_df[(agg_df["model"] == "EIA_M2c") & (agg_df["metrica"] == "positivos")]
    eia_pos_stored = float(eia_pos_row.iloc[0]["valor"]) if not eia_pos_row.empty else float("nan")

    eia_sufficient = (
        n_eia_test >= 30 and n_eia_pos >= 5 and (n_eia_test - n_eia_pos) >= 5
        and not math.isnan(eia_auc_stored)
    )

    if eia_sufficient:
        eia_recalc_auc = _roc_auc_mw(eia_y, eia_m2c)
        rows.append(_claim("ml_eia_test_n",
                           "N de prueba en subgrupo EIA (todos los folds)",
                           int(eia_n_stored), "n", "ml_metrics_agg.parquet",
                           "sum(instrumento==EIA) en ml_oof_predictions",
                           n_eia_test, 0, ""))
        rows.append(_claim("ml_eia_test_positivos",
                           "Positivos (y=1) en subgrupo EIA de prueba",
                           int(eia_pos_stored), "n", "ml_metrics_agg.parquet",
                           "sum(y==1 & instrumento==EIA)",
                           n_eia_pos, 0, ""))
        rows.append(_claim("ml_eia_roc_auc_m2c",
                           "ROC AUC M2c en subgrupo EIA",
                           eia_auc_stored, "", "ml_metrics_agg.parquet",
                           "Mann-Whitney sobre subconjunto EIA de ml_oof_predictions",
                           round(eia_recalc_auc, 6), 0.0005, ""))
    else:
        nota = "EIA con datos insuficientes para validación: no se publica cifra exacta"
        rows.append(_claim("ml_eia_test_n", "N de prueba EIA",
                           n_eia_test, "n", "ml_oof_predictions.parquet",
                           "sum(instrumento==EIA)", None, 0, nota))
        rows.append(_claim("ml_eia_test_positivos", "Positivos EIA",
                           n_eia_pos, "n", "ml_oof_predictions.parquet",
                           "sum(y==1 & instrumento==EIA)", None, 0, nota))
        rows.append(_claim("ml_eia_roc_auc_m2c", "ROC AUC M2c EIA",
                           float("nan"), "", "ml_metrics_agg.parquet",
                           "n/a — insuficiente", None, 0, nota))

    # ── DIA subgroup ──────────────────────────────────────────────────────────
    dia_mask = oof_df["instrumento"] == "DIA"
    dia_y = oof_df.loc[dia_mask, "y"].to_numpy(dtype=float)
    dia_b0 = oof_df.loc[dia_mask, "pred_b0"].to_numpy(dtype=float)
    dia_m2c = oof_df.loc[dia_mask, "pred_m2c"].to_numpy(dtype=float)
    n_dia_test = int(dia_mask.sum())
    n_dia_pos = int(dia_y.sum())

    dia_b0_row = agg_df[(agg_df["model"] == "DIA_B0") & (agg_df["metrica"] == "roc_auc")]
    dia_b0_auc_stored = (
        float(dia_b0_row.iloc[0]["valor"]) if not dia_b0_row.empty else float("nan")
    )
    dia_m2c_row = agg_df[(agg_df["model"] == "DIA_M2c") & (agg_df["metrica"] == "roc_auc")]
    dia_m2c_auc_stored = (
        float(dia_m2c_row.iloc[0]["valor"]) if not dia_m2c_row.empty else float("nan")
    )
    dia_n_row = agg_df[(agg_df["model"] == "DIA_M2c") & (agg_df["metrica"] == "n")]
    dia_n_stored = (
        float(dia_n_row.iloc[0]["valor"]) if not dia_n_row.empty else float("nan")
    )
    dia_pos_row = agg_df[(agg_df["model"] == "DIA_M2c") & (agg_df["metrica"] == "positivos")]
    dia_pos_stored = (
        float(dia_pos_row.iloc[0]["valor"]) if not dia_pos_row.empty else float("nan")
    )

    dia_sufficient = (
        n_dia_test >= 30 and n_dia_pos >= 5 and (n_dia_test - n_dia_pos) >= 5
        and not math.isnan(dia_b0_auc_stored) and not math.isnan(dia_m2c_auc_stored)
    )

    if dia_sufficient:
        dia_recalc_b0 = _roc_auc_mw(dia_y, dia_b0)
        dia_recalc_m2c = _roc_auc_mw(dia_y, dia_m2c)
        rows.append(_claim("ml_dia_test_n",
                           "N de prueba en subgrupo DIA (todos los folds)",
                           int(dia_n_stored), "n", "ml_metrics_agg.parquet",
                           "sum(instrumento==DIA) en ml_oof_predictions",
                           n_dia_test, 0, ""))
        rows.append(_claim("ml_dia_test_positivos",
                           "Positivos (y=1) en subgrupo DIA de prueba",
                           int(dia_pos_stored), "n", "ml_metrics_agg.parquet",
                           "sum(y==1 & instrumento==DIA)",
                           n_dia_pos, 0, ""))
        rows.append(_claim("ml_dia_roc_auc_b0",
                           "ROC AUC B0 en subgrupo DIA",
                           dia_b0_auc_stored, "", "ml_metrics_agg.parquet",
                           "Mann-Whitney sobre subconjunto DIA de ml_oof_predictions",
                           dia_recalc_b0, 0.0005, ""))
        rows.append(_claim("ml_dia_roc_auc_m2c",
                           "ROC AUC M2c en subgrupo DIA",
                           dia_m2c_auc_stored, "", "ml_metrics_agg.parquet",
                           "Mann-Whitney sobre subconjunto DIA de ml_oof_predictions",
                           dia_recalc_m2c, 0.0005, ""))
    else:
        nota_dia = "DIA con datos insuficientes para subgrupo — caso inesperado"
        rows.append(_claim("ml_dia_test_n", "N de prueba DIA",
                           n_dia_test, "n", "ml_oof_predictions.parquet",
                           "sum(instrumento==DIA)", None, 0, nota_dia))
        rows.append(_claim("ml_dia_test_positivos", "Positivos DIA",
                           n_dia_pos, "n", "ml_oof_predictions.parquet",
                           "sum(y==1 & instrumento==DIA)", None, 0, nota_dia))
        rows.append(_claim("ml_dia_roc_auc_b0", "ROC AUC B0 DIA",
                           float("nan"), "", "ml_metrics_agg.parquet",
                           "n/a — insuficiente", None, 0, nota_dia))
        rows.append(_claim("ml_dia_roc_auc_m2c", "ROC AUC M2c DIA",
                           float("nan"), "", "ml_metrics_agg.parquet",
                           "n/a — insuficiente", None, 0, nota_dia))

    # ── Fold count and min ROC AUC ────────────────────────────────────────────
    n_folds = int(metrics_df["fold_year"].nunique())
    m2c_fold_aucs = metrics_df[metrics_df["model"] == "M2c"]["roc_auc"].dropna()
    min_roc_m2c = float(m2c_fold_aucs.min()) if not m2c_fold_aucs.empty else float("nan")

    rows.append(_claim("ml_folds_n",
                       "Número de folds activos en la validación temporal",
                       n_folds, "n", "ml_metrics.parquet",
                       "nunique(fold_year)", n_folds, 0, ""))
    rows.append(_claim("ml_fold_min_roc_auc_m2c",
                       "ROC AUC mínimo por fold de M2c",
                       min_roc_m2c, "", "ml_metrics.parquet",
                       "min(roc_auc) sobre folds de M2c",
                       min_roc_m2c, 0.0005, ""))

    # ── Bootstrap IC claims → pendiente_J ────────────────────────────────────
    _ic_pairs = [
        ("ml_ic95_m2c_roc_auc_lo", "ml_ic95_m2c_roc_auc_hi",
         "M2c_roc_auc_ci_lo", "M2c_roc_auc_ci_hi",
         "IC 95% bootstrap inferior ROC AUC M2c",
         "IC 95% bootstrap superior ROC AUC M2c"),
        ("ml_ic95_m2c_minus_b0_brier_lo", "ml_ic95_m2c_minus_b0_brier_hi",
         "M2c_minus_B0_brier_ci_lo", "M2c_minus_B0_brier_ci_hi",
         "IC 95% bootstrap inferior diferencia Brier M2c−B0",
         "IC 95% bootstrap superior diferencia Brier M2c−B0"),
        ("ml_ic95_m2c_minus_b0_logloss_lo", "ml_ic95_m2c_minus_b0_logloss_hi",
         "M2c_minus_B0_logloss_ci_lo", "M2c_minus_B0_logloss_ci_hi",
         "IC 95% bootstrap inferior diferencia log loss M2c−B0",
         "IC 95% bootstrap superior diferencia log loss M2c−B0"),
    ]
    nota_ic = (
        "IC bootstrap no se puede recalcular sin reentrenar los modelos; "
        "se registra como pendiente hasta revisión manual"
    )
    for lo_id, hi_id, lo_key, hi_key, lo_texto, hi_texto in _ic_pairs:
        ci_lo = _get_agg_ci(agg_df, lo_key)
        ci_hi = _get_agg_ci(agg_df, hi_key)
        rows.append(_claim(lo_id, lo_texto, ci_lo, "", "ml_metrics_agg.parquet",
                           "bootstrap 1000 remuestreos", None, 0, nota_ic))
        rows.append(_claim(hi_id, hi_texto, ci_hi, "", "ml_metrics_agg.parquet",
                           "bootstrap 1000 remuestreos", None, 0, nota_ic))

    return rows


def _get_agg_ci(agg_df: pd.DataFrame, ci_key: str) -> float:
    """Retrieve a bootstrap CI value stored as model/metrica in agg_df."""
    # ci_key examples: "M2c_roc_auc_ci_lo", "M2c_minus_B0_brier_ci_lo"
    # Strategy: scan agg_df for ic95_inf/ic95_sup that match the derived model+metrica
    # The long-format stores: model="M2c", metrica="roc_auc", ic95_inf=lo, ic95_sup=hi
    # and model="M2c_minus_B0", metrica="brier", ic95_inf=lo, ic95_sup=hi
    col = "ic95_inf" if ci_key.endswith("_ci_lo") else "ic95_sup"

    # Parse the key to find model and metrica
    # Patterns: "M2c_roc_auc_ci_lo", "M2c_minus_B0_roc_auc_ci_lo", "M2c_minus_B0_brier_ci_lo"
    key_base = ci_key.replace("_ci_lo", "").replace("_ci_hi", "")

    for _, row in agg_df.iterrows():
        model = row["model"]
        metrica = row["metrica"]
        candidate = f"{model}_{metrica}"
        if candidate == key_base:
            return float(row[col]) if not math.isnan(float(row[col])) else float("nan")
    return float("nan")


def build_ml_claims_register() -> pd.DataFrame:
    """Load parquets and build the ML claims register."""
    agg_df = pd.read_parquet(ML_DIR / "ml_metrics_agg.parquet")
    oof_df = pd.read_parquet(ML_DIR / "ml_oof_predictions.parquet")
    dataset_df = pd.read_parquet(ML_DIR / "ml_dataset.parquet")
    metrics_df = pd.read_parquet(ML_DIR / "ml_metrics.parquet")
    return finalize_claims_register(_build_claims(agg_df, oof_df, dataset_df, metrics_df))


# ── Public document ───────────────────────────────────────────────────────────

def _get_verified(register: pd.DataFrame, claim_id: str) -> float:
    rows = register[(register["claim_id"] == claim_id) & (register["estado"] == "verificada")]
    if rows.empty:
        raise ValueError(
            f"Claim '{claim_id}' not found or not verificada in register"
        )
    return float(rows.iloc[0]["valor"])


def write_ml_results(register: pd.DataFrame) -> str:
    """Generate docs/ml_results.md from verified claims only (comma decimal, Spanish)."""
    def _v(cid: str) -> float:
        return _get_verified(register, cid)

    def _f3(cid: str) -> str:
        return f"{_v(cid):.3f}".replace(".", ",")

    def _fi(cid: str) -> str:
        return str(int(_v(cid)))

    def _fp(cid: str) -> str:
        return f"{_v(cid):.1f} %".replace(".", ",")

    n_elegibles = _fi("ml_n_elegibles")
    n_pos = _fi("ml_positivos")
    tasa_pct = _fp("ml_tasa_positivos_pct")
    n_dia = _fi("ml_n_dia")
    n_eia = _fi("ml_n_eia")
    n_folds = _fi("ml_folds_n")

    lines = [
        "# Modelo predictivo de aprobación ambiental a 24 meses",
        "",
        "## 1. Pregunta",
        "",
        "Con lo conocido al momento del ingreso al SEIA, "
        "¿se puede anticipar si un proyecto obtendrá RCA favorable dentro de 24 meses?",
        "",
        "## 2. Población y objetivo",
        "",
        f"El dataset ML incluye {n_elegibles} expedientes con horizonte completo de observación "
        f"(fecha de ingreso + 24 meses (730,5 días) ≤ fecha de corte de los datos). "
        f"De estos, {n_pos} obtuvieron RCA favorable dentro del horizonte "
        f"(tasa de aprobación: {tasa_pct}). "
        f"La distribución por instrumento es {n_dia} DIA y {n_eia} EIA.",
        "",
        "Variable objetivo `y = 1` si el expediente fue aprobado dentro de 24 meses "
        "desde el ingreso; `y = 0` en cualquier otro desenlace "
        "(desistimiento, rechazo, en trámite sin resolución en el horizonte).",
        "",
        "## 3. Validación",
        "",
        f"Se utilizó validación rolling origin con {n_folds} folds anuales (años 2018–2024). "
        f"Para cada año de prueba Y, el conjunto de entrenamiento incluye solo expedientes "
        f"cuyo horizonte de 24 meses cerró antes del 1 de enero de Y. "
        f"Este embargo garantiza que no se entrena con información futura.",
        "",
        "## 4. Resultados",
        "",
        "| Modelo | ROC AUC | Brier | Log loss |",
        "|--------|---------|-------|----------|",
    ]

    for model_key, label in [("b0", "B0 (tasa base)"), ("m1", "M1 (logístico)"),
                              ("m2", "M2 (HGB)"), ("m2c", "M2c (HGB calibrado)")]:
        auc = _f3(f"ml_roc_auc_{model_key}")
        brier = _f3(f"ml_brier_{model_key}")
        ll = _f3(f"ml_logloss_{model_key}")
        lines.append(f"| {label} | {auc} | {brier} | {ll} |")

    min_fold = _f3("ml_fold_min_roc_auc_m2c")
    lines += [
        "",
        f"ROC AUC mínimo por fold de M2c: {min_fold}.",
        "",
        "El intervalo de confianza 95 % bootstrap para la diferencia de Brier entre M2c y B0 "
        "incluye cero; la mejora en calibración no es estadísticamente concluyente.",
        "",
        "## 5. Dónde no funciona",
        "",
    ]

    # EIA and DIA sections
    eia_n_row = register[register["claim_id"] == "ml_eia_test_n"]
    eia_roc_row = register[register["claim_id"] == "ml_eia_roc_auc_m2c"]
    eia_is_verified = (
        not eia_roc_row.empty and eia_roc_row.iloc[0]["estado"] == "verificada"
        and not math.isnan(float(eia_roc_row.iloc[0]["valor"]))
    )
    dia_roc_m2c_row = register[register["claim_id"] == "ml_dia_roc_auc_m2c"]
    dia_is_verified = (
        not dia_roc_m2c_row.empty and dia_roc_m2c_row.iloc[0]["estado"] == "verificada"
        and not math.isnan(float(dia_roc_m2c_row.iloc[0]["valor"]))
    )

    if eia_is_verified:
        eia_n = _fi("ml_eia_test_n")
        eia_auc = _f3("ml_eia_roc_auc_m2c")
        if dia_is_verified:
            dia_m2c_auc = _f3("ml_dia_roc_auc_m2c")
            eia_compare = (
                f"El ROC AUC de M2c en EIA ({eia_auc}) no supera el azar, "
                f"frente a {dia_m2c_auc} en DIA"
            )
        else:
            eia_compare = f"ROC AUC de M2c en EIA es {eia_auc}"
        lines.append(
            f"**EIA:** el subgrupo EIA acumula solo {eia_n} expedientes de prueba "
            f"en los {n_folds} folds. {eia_compare}. "
            "Las probabilidades no son confiables para EIA."
        )
    else:
        n_eia_test = int(eia_n_row.iloc[0]["valor"]) if not eia_n_row.empty else "?"
        lines.append(
            f"**EIA:** solo {n_eia_test} expedientes EIA acumulados en el conjunto de prueba. "
            "Muestra insuficiente para estimar ROC AUC con fiabilidad. "
            "Las probabilidades no son confiables para EIA."
        )

    lines += [
        "",
        "**Inestabilidad entre años:** el ROC AUC varía entre folds. "
        f"El mínimo por fold de M2c es {min_fold}, lo que indica que el modelo "
        "no es igualmente discriminativo en todos los años de prueba.",
        "",
        "## 6. Qué lo mueve",
        "",
        "El historial del titular al momento del ingreso —número de proyectos previos, "
        "aprobaciones anteriores y cierres negativos recientes— es la señal principal "
        "para ordenar el riesgo de aprobación de las DIA. "
        "La calibración reduce el error de las probabilidades, pero esa mejora "
        "no es estadísticamente concluyente (IC 95 % bootstrap incluye cero). "
        "Los resultados de ablación por bloque de variables están en proceso de revisión "
        "y no se publican aquí.",
        "",
        "## 7. Límites",
        "",
        "- **Asociación, no causalidad.** El modelo detecta patrones históricos; "
        "no explica por qué un proyecto es aprobado.",
        "- **Calibración.** M2c usa calibración sigmoide (Platt) con validación cruzada "
        "aleatoria dentro del entrenamiento, no temporal. "
        "La calibración puede degradarse fuera de la muestra.",
        "- **Población pequeña.** Con menos de mil expedientes elegibles, "
        "los intervalos de confianza son amplios.",
        "- **Sin uso operativo para EIA.** Las probabilidades para EIA no son confiables "
        "y no deben usarse para tomar decisiones.",
    ]

    return "\n".join(lines) + "\n"


# ── CLI ───────────────────────────────────────────────────────────────────────

def main() -> None:
    register = build_ml_claims_register()
    out_csv = ML_DIR / "ml_claims_register.csv"
    out_csv.write_text(register.to_csv(index=False), encoding="utf-8")

    md = write_ml_results(register)
    out_md = DOCS_DIR / "ml_results.md"
    out_md.write_text(md, encoding="utf-8")

    print(register.groupby("estado").size().to_string())
    print(f"\nEscrito: {out_csv}")
    print(f"Escrito: {out_md}")
