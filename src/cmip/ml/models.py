"""Model definitions for 24-month approval prediction."""
from __future__ import annotations

import numpy as np
import pandas as pd
from sklearn.base import BaseEstimator, TransformerMixin
from sklearn.calibration import CalibratedClassifierCV
from sklearn.compose import ColumnTransformer
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder, StandardScaler

from cmip.ml.features import NUMERIC_FEATURES

RANDOM_STATE = 42
LR_C = 1.0
HGB_PARAMS = {
    "max_depth": 3,
    "learning_rate": 0.05,
    "max_iter": 300,
    "min_samples_leaf": 20,
    "l2_regularization": 1.0,
    "random_state": RANDOM_STATE,
}
_RARE_THRESHOLD = 10


class RareCategoryGrouper(BaseEstimator, TransformerMixin):
    """Group infrequent categories into 'otra' during fit; apply on transform."""

    def __init__(self, threshold: int = _RARE_THRESHOLD) -> None:
        self.threshold = threshold

    def fit(self, X: pd.Series, y=None) -> RareCategoryGrouper:
        counts = X.value_counts()
        self.frequent_: frozenset[str] = frozenset(
            counts.index[counts >= self.threshold]
        )
        return self

    def transform(self, X: pd.Series) -> pd.Series:
        return X.where(X.isin(self.frequent_), other="otra")


class _RareCategoryGrouperColumn(BaseEstimator, TransformerMixin):
    """Wrap RareCategoryGrouper to work on a single-column DataFrame."""

    def __init__(self, threshold: int = _RARE_THRESHOLD) -> None:
        self.threshold = threshold

    def fit(self, X, y=None):
        self.groupers_: dict[str, RareCategoryGrouper] = {}
        if hasattr(X, "columns"):
            for col in X.columns:
                g = RareCategoryGrouper(self.threshold)
                g.fit(X[col])
                self.groupers_[col] = g
        else:
            g = RareCategoryGrouper(self.threshold)
            g.fit(pd.Series(X.ravel()))
            self.groupers_["_"] = g
        return self

    def transform(self, X):
        if hasattr(X, "columns"):
            out = X.copy()
            for col in X.columns:
                if col in self.groupers_:
                    out[col] = self.groupers_[col].transform(X[col])
            return out
        s = pd.Series(X.ravel())
        return self.groupers_["_"].transform(s).values.reshape(-1, 1)

    def get_feature_names_out(self, input_features=None):
        if input_features is not None:
            return list(input_features)
        return list(self.groupers_.keys())


_RARE_CATS = ["tipologia", "region"]
_PLAIN_CATS = ["instrumento", "macro_zona"]


def _build_preprocessor(
    numeric_features: list[str] | None = None,
    rare_cats: list[str] | None = None,
    plain_cats: list[str] | None = None,
) -> ColumnTransformer:
    if numeric_features is None:
        numeric_features = NUMERIC_FEATURES
    if rare_cats is None:
        rare_cats = _RARE_CATS
    if plain_cats is None:
        plain_cats = _PLAIN_CATS

    rare_pipeline = Pipeline([
        ("grouper", _RareCategoryGrouperColumn(_RARE_THRESHOLD)),
        ("ohe", OneHotEncoder(handle_unknown="ignore", sparse_output=False)),
    ])

    plain_pipeline = Pipeline([
        ("ohe", OneHotEncoder(handle_unknown="ignore", sparse_output=False)),
    ])

    transformers = [("num", StandardScaler(), numeric_features)]
    if rare_cats:
        transformers.append(("cat_rare", rare_pipeline, rare_cats))
    if plain_cats:
        transformers.append(("cat_plain", plain_pipeline, plain_cats))

    return ColumnTransformer(transformers=transformers, remainder="drop")


def build_logistic_pipeline(
    numeric_features: list[str] | None = None,
    rare_cats: list[str] | None = None,
    plain_cats: list[str] | None = None,
) -> Pipeline:
    return Pipeline([
        ("pre", _build_preprocessor(numeric_features, rare_cats, plain_cats)),
        ("clf", LogisticRegression(C=LR_C, random_state=RANDOM_STATE, max_iter=1000)),
    ])


def build_hgb_pipeline(
    numeric_features: list[str] | None = None,
    rare_cats: list[str] | None = None,
    plain_cats: list[str] | None = None,
) -> Pipeline:
    return Pipeline([
        ("pre", _build_preprocessor(numeric_features, rare_cats, plain_cats)),
        ("clf", HistGradientBoostingClassifier(**HGB_PARAMS)),
    ])


def build_m2c_pipeline(
    numeric_features: list[str] | None = None,
    rare_cats: list[str] | None = None,
    plain_cats: list[str] | None = None,
) -> CalibratedClassifierCV:
    """M2 with Platt calibration (sigmoid, cv=5)."""
    base = build_hgb_pipeline(numeric_features, rare_cats, plain_cats)
    return CalibratedClassifierCV(base, method="sigmoid", cv=5)


def baseline_predict(train: pd.DataFrame, test: pd.DataFrame) -> np.ndarray:
    """B0: predict the per-instrument y rate from training data."""
    rates = train.groupby("instrumento")["y"].mean().to_dict()
    overall = train["y"].mean()
    return test["instrumento"].map(rates).fillna(overall).to_numpy()


def fit_logistic(
    X_train: pd.DataFrame,
    y_train: pd.Series,
    numeric_features: list[str] | None = None,
    rare_cats: list[str] | None = None,
    plain_cats: list[str] | None = None,
) -> Pipeline:
    pipeline = build_logistic_pipeline(numeric_features, rare_cats, plain_cats)
    pipeline.fit(X_train, y_train)
    return pipeline


def fit_hgb(
    X_train: pd.DataFrame,
    y_train: pd.Series,
    numeric_features: list[str] | None = None,
    rare_cats: list[str] | None = None,
    plain_cats: list[str] | None = None,
) -> Pipeline:
    pipeline = build_hgb_pipeline(numeric_features, rare_cats, plain_cats)
    pipeline.fit(X_train, y_train)
    return pipeline


def fit_m2c(
    X_train: pd.DataFrame,
    y_train: pd.Series,
    numeric_features: list[str] | None = None,
    rare_cats: list[str] | None = None,
    plain_cats: list[str] | None = None,
) -> CalibratedClassifierCV:
    pipeline = build_m2c_pipeline(numeric_features, rare_cats, plain_cats)
    pipeline.fit(X_train, y_train)
    return pipeline


def extract_logit_coefs(pipeline: Pipeline) -> pd.DataFrame:
    """Return a DataFrame of coefficient, odds_ratio, feature for the LR pipeline."""
    pre = pipeline.named_steps["pre"]
    clf = pipeline.named_steps["clf"]

    names = list(pre.get_feature_names_out())

    coefs = clf.coef_.ravel()
    return pd.DataFrame({
        "feature": names,
        "coefficient": coefs,
        "odds_ratio": np.exp(coefs),
    }).sort_values("odds_ratio", ascending=False).reset_index(drop=True)
