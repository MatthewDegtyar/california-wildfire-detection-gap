"""Detection-gap model: P(FIRMS detects fire | fire characteristics).

Two models compared head-to-head against baselines from src.baselines:
  - Logistic regression with scaled continuous features + one-hot cause
  - Gradient-boosted trees (sklearn HistGradientBoostingClassifier)

Both are wrapped in CalibratedClassifierCV (isotonic, 5-fold) so the probabilities
we report are honestly calibrated — start.md is explicit on this: "Calibration
is verified by held-out coverage, not in-sample accuracy."

Evaluation: out-of-fold predictions from a 5-fold stratified CV; report Brier,
log-loss, ROC-AUC. Save OOF predictions and reliability bins for plotting,
plus a final model fit on all data and persisted for the gap-surface step.
"""

from __future__ import annotations

import pickle

import numpy as np
import pandas as pd
from sklearn.calibration import CalibratedClassifierCV
from sklearn.compose import ColumnTransformer
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.impute import SimpleImputer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import brier_score_loss, log_loss, roc_auc_score
from sklearn.model_selection import StratifiedKFold
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder, StandardScaler

from src.config import PROCESSED
from src.features import load_modeling_frame

RNG = 0

NUMERIC = ["log_size", "LATITUDE", "LONGITUDE", "sin_doy", "cos_doy",
           "disc_hour", "hours_since_overpass"]
CATEGORICAL = ["cause"]


def _logreg() -> Pipeline:
    return Pipeline([
        ("pre", ColumnTransformer([
            ("num", Pipeline([
                ("imp", SimpleImputer(strategy="median")),
                ("sc", StandardScaler()),
            ]), NUMERIC),
            ("cat", OneHotEncoder(handle_unknown="ignore", min_frequency=10), CATEGORICAL),
        ])),
        ("clf", LogisticRegression(max_iter=2000, C=1.0, class_weight="balanced", random_state=RNG)),
    ])


def _gbm() -> Pipeline:
    return Pipeline([
        ("pre", ColumnTransformer([
            ("num", "passthrough", NUMERIC),  # HGB handles NaN natively
            ("cat", OneHotEncoder(handle_unknown="ignore", min_frequency=10, sparse_output=False), CATEGORICAL),
        ])),
        ("clf", HistGradientBoostingClassifier(
            max_iter=300, learning_rate=0.05, max_depth=5,
            l2_regularization=1.0, random_state=RNG,
        )),
    ])


def evaluate_oof(model_factory, X, y, n_splits=5):
    skf = StratifiedKFold(n_splits=n_splits, shuffle=True, random_state=RNG)
    p_oof = np.zeros(len(y))
    for tr, te in skf.split(X, y):
        # CalibratedClassifierCV with inner CV gives held-out calibration
        m = CalibratedClassifierCV(model_factory(), method="isotonic", cv=5)
        m.fit(X.iloc[tr], y[tr])
        p_oof[te] = m.predict_proba(X.iloc[te])[:, 1]
    return p_oof


def reliability_bins(y, p, n_bins=10):
    bins = np.linspace(0, 1, n_bins + 1)
    idx = np.clip(np.digitize(p, bins, right=False) - 1, 0, n_bins - 1)
    rows = []
    for b in range(n_bins):
        sel = idx == b
        if sel.sum() == 0:
            continue
        rows.append({
            "bin_low": bins[b], "bin_high": bins[b + 1],
            "n": int(sel.sum()),
            "mean_pred": float(p[sel].mean()),
            "mean_actual": float(y[sel].mean()),
        })
    return pd.DataFrame(rows)


def _metrics(name, y, p):
    return {
        "model": name,
        "brier": brier_score_loss(y, p),
        "log_loss": log_loss(y, np.clip(p, 1e-6, 1 - 1e-6)),
        "auc": roc_auc_score(y, p),
        "mean_pred": float(p.mean()),
        "mean_actual": float(y.mean()),
    }


def main():
    df = load_modeling_frame().reset_index(drop=True)
    y = df["firms_hit"].astype(int).values
    X = df[NUMERIC + CATEGORICAL]

    print("Evaluating logistic regression (5-fold OOF, isotonic-calibrated)...")
    p_lr = evaluate_oof(_logreg, X, y)
    print("Evaluating gradient boost (5-fold OOF, isotonic-calibrated)...")
    p_gb = evaluate_oof(_gbm, X, y)

    rows = [_metrics("logreg_calibrated", y, p_lr),
            _metrics("gbm_calibrated", y, p_gb)]
    print("\nModel metrics (OOF):")
    print(pd.DataFrame(rows).to_string(index=False, float_format=lambda x: f"{x:.4f}"))

    # Save OOF + reliability
    out = df[["FOD_ID", "FIRE_SIZE", "FIRE_SIZE_CLASS", "LATITUDE", "LONGITUDE",
              "firms_hit"]].copy()
    out["p_logreg"] = p_lr
    out["p_gbm"] = p_gb
    out.to_parquet(PROCESSED / "model_oof.parquet", index=False)

    rel_lr = reliability_bins(y, p_lr)
    rel_gb = reliability_bins(y, p_gb)
    rel_lr["model"] = "logreg_calibrated"
    rel_gb["model"] = "gbm_calibrated"
    pd.concat([rel_lr, rel_gb], ignore_index=True).to_parquet(
        PROCESSED / "model_reliability.parquet", index=False
    )

    pd.DataFrame(rows).to_parquet(PROCESSED / "model_metrics.parquet", index=False)
    print(f"\nwrote -> {PROCESSED / 'model_oof.parquet'}, model_reliability.parquet, model_metrics.parquet")

    # Final model fit on all data, persisted for the gap-surface step.
    print("\nFitting final calibrated GBM on all data...")
    final = CalibratedClassifierCV(_gbm(), method="isotonic", cv=5)
    final.fit(X, y)
    with (PROCESSED / "final_model.pkl").open("wb") as f:
        pickle.dump(final, f)
    print(f"wrote -> {PROCESSED / 'final_model.pkl'}")


if __name__ == "__main__":
    main()
