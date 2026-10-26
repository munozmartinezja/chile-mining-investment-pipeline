"""Tests for ML claims register: schema, prefix, uniqueness, verified claims, README guard."""
from __future__ import annotations

import re
from pathlib import Path

import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[2]
README = ROOT / "README.md"

_ML_PARQUETS = [
    ROOT / "data/ml/ml_dataset.parquet",
    ROOT / "data/ml/ml_oof_predictions.parquet",
    ROOT / "data/ml/ml_metrics_agg.parquet",
    ROOT / "data/ml/ml_metrics.parquet",
]
requires_local_data = pytest.mark.skipif(
    not all(p.exists() for p in _ML_PARQUETS),
    reason="requires data/ml/ parquets from make ml",
)

_MINIMUM_VERIFIED_CLAIMS = [
    "ml_n_elegibles",
    "ml_positivos",
    "ml_tasa_positivos_pct",
    "ml_n_dia",
    "ml_n_eia",
    "ml_roc_auc_b0",
    "ml_roc_auc_m1",
    "ml_roc_auc_m2",
    "ml_roc_auc_m2c",
    "ml_brier_b0",
    "ml_brier_m2c",
    "ml_logloss_b0",
    "ml_logloss_m2c",
    "ml_brier_skill_m2c",
    "ml_folds_n",
    "ml_fold_min_roc_auc_m2c",
    "ml_dia_test_n",
    "ml_dia_test_positivos",
    "ml_dia_roc_auc_b0",
    "ml_dia_roc_auc_m2c",
]


@pytest.fixture(scope="module")
def register():
    from cmip.ml.claims import build_ml_claims_register

    return build_ml_claims_register()


# ── Structural tests (need the local data/ml/ outputs) ────────────────────────

@requires_local_data
def test_claims_schema_columns(register):
    from cmip.validation import CLAIM_COLUMNS

    assert set(register.columns) == set(CLAIM_COLUMNS), (
        f"Extra: {set(register.columns) - set(CLAIM_COLUMNS)}, "
        f"Missing: {set(CLAIM_COLUMNS) - set(register.columns)}"
    )


@requires_local_data
def test_claims_prefix(register):
    bad = [cid for cid in register["claim_id"] if not cid.startswith("ml_")]
    assert bad == [], f"claim_ids without 'ml_' prefix: {bad}"


@requires_local_data
def test_claims_unique(register):
    dupes = register[register["claim_id"].duplicated()]["claim_id"].tolist()
    assert dupes == [], f"Duplicate claim_ids: {dupes}"


def test_no_c1_imports_ml():
    """Isolation: no C1 module outside src/cmip/ml/ imports cmip.ml.*"""
    import ast

    src = ROOT / "src" / "cmip"
    violations: list[str] = []

    for py_file in src.rglob("*.py"):
        if "cmip/ml" in str(py_file).replace("\\", "/"):
            continue
        try:
            tree = ast.parse(py_file.read_text(encoding="utf-8"), filename=str(py_file))
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            mod = None
            if isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name.startswith("cmip.ml"):
                        mod = alias.name
            elif (  # noqa: SIM102
                isinstance(node, ast.ImportFrom)
                and node.module
                and node.module.startswith("cmip.ml")
            ):
                mod = node.module
            if mod:
                violations.append(f"{py_file.relative_to(src.parent.parent)}: imports {mod}")

    assert violations == [], "\n".join(violations)


# ── Local-data tests ──────────────────────────────────────────────────────────

@requires_local_data
@pytest.mark.parametrize("claim_id", _MINIMUM_VERIFIED_CLAIMS)
def test_minimum_claims_verified(register, claim_id):
    rows = register[register["claim_id"] == claim_id]
    assert not rows.empty, f"Claim '{claim_id}' not found in register"
    estado = rows.iloc[0]["estado"]
    assert estado == "verificada", (
        f"Claim '{claim_id}' has estado='{estado}', expected 'verificada'"
    )


@requires_local_data
def test_roc_auc_recalc_matches_sklearn(register):
    """Mann-Whitney ROC AUC recalculation matches sklearn within 1e-9."""
    sklearn = pytest.importorskip("sklearn")  # noqa: F841
    from sklearn.metrics import roc_auc_score

    from cmip.ml.claims import _roc_auc_mw

    oof = pd.read_parquet(ROOT / "data/ml/ml_oof_predictions.parquet")
    y = oof["y"].to_numpy(dtype=float)
    p = oof["pred_m2c"].to_numpy(dtype=float)

    mw_auc = _roc_auc_mw(y, p)
    sk_auc = roc_auc_score(y, p)
    assert abs(mw_auc - sk_auc) < 1e-9, (
        f"Mann-Whitney AUC {mw_auc:.10f} differs from sklearn {sk_auc:.10f} by "
        f"{abs(mw_auc - sk_auc):.2e}"
    )


def _build_claim_value_lookup(register: pd.DataFrame) -> dict[str, list[str]]:
    """Map formatted decimal string (period form) → claim_ids for all dp levels 1-5."""
    verified = register[register["estado"] == "verificada"]
    lookup: dict[str, list[str]] = {}
    for _, row in verified.iterrows():
        try:
            v = float(row["valor"])
        except (TypeError, ValueError):
            continue
        for dp in range(1, 6):
            key = f"{v:.{dp}f}"
            lookup.setdefault(key, []).append(row["claim_id"])
    return lookup


@requires_local_data
def test_readme_ml_claims_guard(register):
    """ES C1-ML uses comma decimal; EN C1-ML uses period decimal; all match verified claims."""
    readme = README.read_text(encoding="utf-8")

    es_match = re.search(
        r"### Modelo predictivo \(C1-ML\)(.*?)(?=\n###|\n---|\Z)", readme, re.DOTALL
    )
    en_match = re.search(
        r"### Predictive model \(C1-ML\)(.*?)(?=\n###|\n---|\Z)", readme, re.DOTALL
    )
    assert es_match, "README missing '### Modelo predictivo (C1-ML)' subsection"
    assert en_match, "README missing '### Predictive model (C1-ML)' subsection"

    es_text = es_match.group(1)
    en_text = en_match.group(1)

    lookup = _build_claim_value_lookup(register)

    # ES section: comma decimal required; period decimal forbidden
    period_in_es = re.findall(r"\b(\d+\.\d+)\b", es_text)
    assert period_in_es == [], (
        f"ES C1-ML section uses period decimal (should use comma): {period_in_es}"
    )
    comma_nums_es = re.findall(r"\b(\d+,\d+)\b", es_text)
    unverified_es = []
    for num_str in comma_nums_es:
        period_form = num_str.replace(",", ".")
        dp = len(period_form.split(".")[-1])
        key = f"{float(period_form):.{dp}f}"
        if key not in lookup:
            unverified_es.append(num_str)
    assert unverified_es == [], (
        f"Numbers in ES README C1-ML section not matching verified claims: {unverified_es}"
    )

    # EN section: period decimal required; comma decimal forbidden
    comma_in_en = re.findall(r"\b(\d+,\d+)\b", en_text)
    assert comma_in_en == [], (
        f"EN C1-ML section uses comma decimal (should use period): {comma_in_en}"
    )
    period_nums_en = re.findall(r"\b(\d+\.\d+)\b", en_text)
    unverified_en = []
    for num_str in period_nums_en:
        dp = len(num_str.split(".")[-1])
        key = f"{float(num_str):.{dp}f}"
        if key not in lookup:
            unverified_en.append(num_str)
    assert unverified_en == [], (
        f"Numbers in EN README C1-ML section not matching verified claims: {unverified_en}"
    )


# Known non-metric constants that appear in docs/ml_results.md
_ML_RESULTS_NON_METRIC_ES = frozenset({"730,5"})


@requires_local_data
def test_ml_results_doc_only_verified(register):
    """docs/ml_results.md uses comma decimal; all metric numbers match verified claims."""
    ml_results = ROOT / "docs" / "ml_results.md"
    if not ml_results.exists():
        pytest.skip("docs/ml_results.md not generated yet; run make ml-claims")

    text = ml_results.read_text(encoding="utf-8")

    # Doc is Spanish: must use comma decimals; period decimals are wrong
    period_nums = re.findall(r"\b(\d+\.\d+)\b", text)
    assert period_nums == [], (
        f"docs/ml_results.md contains period-decimal numbers (should use comma): {period_nums}"
    )

    comma_nums = re.findall(r"\b(\d+,\d+)\b", text)
    metric_nums = [n for n in comma_nums if n not in _ML_RESULTS_NON_METRIC_ES]

    lookup = _build_claim_value_lookup(register)

    non_verified = []
    for num_str in metric_nums:
        period_form = num_str.replace(",", ".")
        dp = len(period_form.split(".")[-1])
        key = f"{float(period_form):.{dp}f}"
        if key not in lookup:
            non_verified.append(num_str)

    assert non_verified == [], (
        f"docs/ml_results.md contains comma-decimal numbers not matching verified claims: "
        f"{non_verified}"
    )


@requires_local_data
def test_valor_not_pre_rounded(register):
    """No float valor stored at exactly 3dp unless recalc also rounds to same value."""
    import math

    verified = register[register["estado"] == "verificada"]
    violations = []
    for _, row in verified.iterrows():
        try:
            v = float(row["valor"])
            vr = float(row["valor_recalculado"])
        except (TypeError, ValueError):
            continue
        if math.isnan(v) or math.isnan(vr):
            continue
        if v == round(v, 0):  # integer value — skip
            continue
        if round(v, 3) == v and round(vr, 3) != v:
            violations.append(
                f"{row['claim_id']}: valor={v} (3dp) but recalc={vr} "
                f"rounds to {round(vr, 3)} ≠ {v}"
            )
    assert violations == [], "\n".join(violations)


@requires_local_data
def test_eia_claims_verified_or_pending(register):
    """EIA and DIA subgroup claims are verificada or pendiente_autor."""
    subgroup_claims = [
        "ml_eia_test_n", "ml_eia_test_positivos", "ml_eia_roc_auc_m2c",
        "ml_dia_test_n", "ml_dia_test_positivos", "ml_dia_roc_auc_b0", "ml_dia_roc_auc_m2c",
    ]
    for cid in subgroup_claims:
        rows = register[register["claim_id"] == cid]
        assert not rows.empty, f"Claim '{cid}' not found"
        estado = rows.iloc[0]["estado"]
        assert estado in {"verificada", "pendiente_autor"}, (
            f"Claim '{cid}' has unexpected estado='{estado}'"
        )


@requires_local_data
def test_bootstrap_ic_claims_are_pending(register):
    """Bootstrap IC claims are all pendiente_autor."""
    ic_claims = register[register["claim_id"].str.startswith("ml_ic95_")]
    assert len(ic_claims) > 0, "No bootstrap IC claims found"
    non_pending = ic_claims[ic_claims["estado"] != "pendiente_autor"]
    assert len(non_pending) == 0, (
        f"Bootstrap IC claims not pendiente_autor: {non_pending['claim_id'].tolist()}"
    )


@requires_local_data
def test_roc_auc_values_consistent_with_known_range(register):
    """Sanity: all ROC AUC values are in (0.5, 1.0) for non-baseline models."""
    for cid in ["ml_roc_auc_m1", "ml_roc_auc_m2", "ml_roc_auc_m2c"]:
        rows = register[(register["claim_id"] == cid) & (register["estado"] == "verificada")]
        if rows.empty:
            continue
        v = float(rows.iloc[0]["valor"])
        assert 0.5 < v < 1.0, f"ROC AUC {cid}={v} outside expected range (0.5, 1.0)"


@requires_local_data
def test_brier_skill_positive_for_m2c(register):
    """Brier skill of M2c is positive (better than baseline)."""
    rows = register[
        (register["claim_id"] == "ml_brier_skill_m2c") & (register["estado"] == "verificada")
    ]
    assert not rows.empty, "ml_brier_skill_m2c not verified"
    v = float(rows.iloc[0]["valor"])
    assert v > 0, f"Brier skill of M2c is {v}, expected > 0"


@requires_local_data
def test_n_elegibles_matches_dataset(register):
    """ml_n_elegibles matches actual row count in ml_dataset.parquet."""
    dataset = pd.read_parquet(ROOT / "data/ml/ml_dataset.parquet")
    rows = register[register["claim_id"] == "ml_n_elegibles"]
    assert not rows.empty
    assert int(rows.iloc[0]["valor"]) == len(dataset)


@requires_local_data
def test_revision_claims_publish_2024_sensitivity_and_m2_ablation(register):
    indexed = register.set_index("claim_id")

    assert indexed.loc["ml_dia_roc_auc_m2c_sin_2024", "valor"] == pytest.approx(
        0.7438156882850551
    )
    assert indexed.loc["ml_roc_auc_m2_completo_ablacion", "valor"] == pytest.approx(
        0.7448099829835507
    )
    assert indexed.loc["ml_roc_auc_m2_sin_titular", "valor"] == pytest.approx(
        0.6488938298830305
    )
    assert set(register["tipo_verificacion"]) <= {
        "independiente",
        "control_aritmetico",
        "replica",
    }
