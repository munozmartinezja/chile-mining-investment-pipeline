"""CLI entry point: python -m cmip.ml features | train."""
from __future__ import annotations

import argparse

import pandas as pd

from cmip.config import PROJECT_ROOT

ML_DIR = PROJECT_ROOT / "data" / "ml"


def _ensure_ml_dir() -> None:
    ML_DIR.mkdir(parents=True, exist_ok=True)


def cmd_features(args: argparse.Namespace) -> None:
    from cmip.ml.dataset import load_ml_population

    _ensure_ml_dir()
    dataset = load_ml_population()
    out = ML_DIR / "ml_dataset.parquet"
    dataset.to_parquet(out, index=False)
    print(f"Saved {len(dataset)} rows → {out}")
    print(f"  y=1: {dataset['y'].sum()}  y=0: {(dataset['y'] == 0).sum()}")


def _draft_summary(dataset: pd.DataFrame, oof_result) -> str:
    agg = oof_result.metrics_agg
    ci = oof_result.bootstrap_ci
    eia = oof_result.eia_metrics
    mdf = oof_result.metrics_by_fold

    lines = [
        "Borrador — cifras no registradas; no publicar",
        "",
        f"Población elegible: n={len(dataset)}, positivos={dataset['y'].sum()}",
        "",
        "## Métricas OOF agregadas",
        "",
        "| Modelo | ROC AUC | IC 95% | Media folds | Mín fold |"
        " PR AUC | Brier | Brier skill | Log loss |",
        "|--------|---------|--------|-------------|----------|"
        "--------|-------|-------------|----------|",
    ]

    for m in ["B0", "M1", "M2", "M2c"]:
        a = agg[m]
        lo = ci.get(f"{m}_roc_auc_ci_lo", float("nan"))
        hi = ci.get(f"{m}_roc_auc_ci_hi", float("nan"))
        bs = a["brier_skill"]
        med = a.get("roc_auc_media_folds", float("nan"))
        mn = a.get("roc_auc_min_fold", float("nan"))
        lines.append(
            f"| {m} | {a['roc_auc']:.3f} | [{lo:.3f}, {hi:.3f}] |"
            f" {med:.3f} | {mn:.3f} |"
            f" {a['pr_auc']:.3f} | {a['brier']:.3f} | {bs:.3f}"
            f" | {a['log_loss']:.3f} |"
        )

    lines += ["", "## Diferencias bootstrap vs B0", ""]
    for key in ["M2_minus_B0", "M1_minus_B0", "M2c_minus_B0"]:
        lo = ci.get(f"{key}_ci_lo", float("nan"))
        hi = ci.get(f"{key}_ci_hi", float("nan"))
        lines.append(f"- {key}: IC 95% [{lo:.3f}, {hi:.3f}]")

    # E2: fold table
    lines += ["", "## Métricas por fold", ""]
    fold_table_hdr = "| Año | n | positivos | ROC B0 | ROC M1 | ROC M2 | ROC M2c |"
    fold_table_sep = "|-----|---|-----------|--------|--------|--------|---------|"
    lines += [fold_table_hdr, fold_table_sep]

    fold_years = sorted(mdf["fold_year"].unique())
    for yr in fold_years:
        yr_df = mdf[mdf["fold_year"] == yr]
        n_yr = yr_df[yr_df["model"] == "B0"]["n"].values
        pos_yr = yr_df[yr_df["model"] == "B0"]["positivos"].values
        n_str = str(n_yr[0]) if len(n_yr) > 0 else "?"
        pos_str = str(pos_yr[0]) if len(pos_yr) > 0 else "?"

        def _auc(ydf: pd.DataFrame, model: str) -> str:
            v = ydf[ydf["model"] == model]["roc_auc"].values
            return f"{v[0]:.3f}" if len(v) > 0 else "?"

        lines.append(
            f"| {yr} | {n_str} | {pos_str}"
            f" | {_auc(yr_df, 'B0')} | {_auc(yr_df, 'M1')}"
            f" | {_auc(yr_df, 'M2')} | {_auc(yr_df, 'M2c')} |"
        )

    # E4: EIA metrics
    lines += ["", "## Subgrupo EIA", ""]
    for m in ["M1", "M2", "M2c"]:
        em = eia.get(m, {})
        if isinstance(em, dict) and em.get("resultado") == "insuficiente":
            lines.append(f"**{m}**: Insuficiente — {em['motivo']}")
        elif isinstance(em, dict) and "roc_auc" in em:
            lines.append(
                f"**{m}**: n={em['n']}, positivos={em['positivos']},"
                f" ROC AUC={em['roc_auc']:.3f}, Brier={em['brier']:.3f}"
            )

    # E3: ablation table
    lines += ["", "## Ablación", ""]
    abl = oof_result.ablation
    if not abl.empty:
        lines += [
            "| Bloque quitado | Modelo | ROC AUC OOF | Delta vs completo |",
            "|----------------|--------|-------------|-------------------|",
        ]
        for _, row in abl.iterrows():
            lines.append(
                f"| {row['bloque_quitado']} | {row['modelo']}"
                f" | {row['roc_auc_oof']:.3f} | {row['delta_vs_completo']:+.3f} |"
            )

    if oof_result.skipped:
        lines += ["", "## Folds omitidos", ""]
        for s in oof_result.skipped:
            lines.append(f"- {s['year']}: {s['reason']}")

    return "\n".join(lines) + "\n"


def cmd_train(args: argparse.Namespace) -> None:
    from cmip.ml.dataset import load_ml_population
    from cmip.ml.evaluate import run_oof
    from cmip.ml.split import temporal_split

    _ensure_ml_dir()

    dataset_path = ML_DIR / "ml_dataset.parquet"
    if dataset_path.exists():
        dataset = pd.read_parquet(dataset_path)
        print(f"Loaded dataset from cache ({len(dataset)} rows)")
    else:
        dataset = load_ml_population()
        dataset.to_parquet(dataset_path, index=False)
        print(f"Built and saved dataset ({len(dataset)} rows)")

    split = temporal_split(dataset)
    print(f"Folds: {len(split.folds)} activos, {len(split.skipped)} omitidos")

    oof = run_oof(dataset, split)

    oof.predictions.to_parquet(ML_DIR / "ml_oof_predictions.parquet", index=False)
    oof.metrics_by_fold.to_parquet(ML_DIR / "ml_metrics.parquet", index=False)
    oof.calibration.to_parquet(ML_DIR / "ml_calibration.parquet", index=False)
    oof.logit_coefs.to_parquet(ML_DIR / "ml_logit_coefs.parquet", index=False)
    oof.ablation.to_parquet(ML_DIR / "ml_ablation.parquet", index=False)

    draft = _draft_summary(dataset, oof)
    (ML_DIR / "ml_results_draft.md").write_text(draft, encoding="utf-8")

    print("\nMétricas OOF agregadas:")
    for model, m in oof.metrics_agg.items():
        print(f"  {model}: ROC AUC={m['roc_auc']:.3f}  Brier skill={m['brier_skill']:.3f}")

    print(f"\nSalidas escritas en {ML_DIR}/")


def main() -> None:
    parser = argparse.ArgumentParser(prog="python -m cmip.ml")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("features", help="Build and save ML dataset")
    sub.add_parser("train", help="Run split, train models, evaluate OOF")
    args = parser.parse_args()

    if args.command == "features":
        cmd_features(args)
    elif args.command == "train":
        cmd_train(args)


if __name__ == "__main__":
    main()
