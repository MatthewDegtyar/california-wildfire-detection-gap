"""Ablation: does the v1 GBM still beat the size-class baseline if we drop
the hardcoded `hours_since_overpass` feature?

The reviewer's worry: hours_since_overpass is built on a hardcoded 02:00/14:00
local schedule (Suomi-NPP overpasses) and is NaN for ~22% of records (those
without DISCOVERY_TIME). If the v1 GBM's lift over the size-class baseline is
partly attributable to that feature, the "continuous features buy real lift"
claim is on shakier ground than the headline metrics suggest.

This script refits the same v1 GBM pipeline with `hours_since_overpass`
removed from the feature set, runs 5-fold OOF, and reports per-fold mean ± std
alongside the original v1 numbers. If the ablated model is within 1σ of the
full model, the feature is not load-bearing.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
from sklearn.calibration import CalibratedClassifierCV
from sklearn.compose import ColumnTransformer
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.metrics import brier_score_loss, log_loss, roc_auc_score
from sklearn.model_selection import StratifiedKFold
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder

from src.config import PROCESSED
from src.features import load_modeling_frame

RNG = 0

NUMERIC_FULL = ["log_size", "LATITUDE", "LONGITUDE", "sin_doy", "cos_doy",
                "disc_hour", "hours_since_overpass"]
NUMERIC_ABLATED = ["log_size", "LATITUDE", "LONGITUDE", "sin_doy", "cos_doy",
                   "disc_hour"]
CATEGORICAL = ["cause"]


def _gbm(numeric_cols) -> Pipeline:
    return Pipeline([
        ("pre", ColumnTransformer([
            ("num", "passthrough", numeric_cols),
            ("cat", OneHotEncoder(handle_unknown="ignore", min_frequency=10, sparse_output=False),
             CATEGORICAL),
        ])),
        ("clf", HistGradientBoostingClassifier(
            max_iter=300, learning_rate=0.05, max_depth=5,
            l2_regularization=1.0, random_state=RNG,
        )),
    ])


def _per_fold(y_true, p, folds):
    rows = []
    for k, (_, te) in enumerate(folds):
        yt = y_true[te]
        pt = np.clip(p[te], 1e-6, 1 - 1e-6)
        rows.append({
            "fold": k,
            "brier": brier_score_loss(yt, pt),
            "log_loss": log_loss(yt, pt),
            "auc": roc_auc_score(yt, pt) if len(np.unique(yt)) >= 2 else np.nan,
        })
    return pd.DataFrame(rows)


def _evaluate(label, numeric_cols, df, y, folds):
    X = df[numeric_cols + CATEGORICAL]
    p_oof = np.zeros(len(y))
    for tr, te in folds:
        m = CalibratedClassifierCV(_gbm(numeric_cols), method="isotonic", cv=5)
        m.fit(X.iloc[tr], y[tr])
        p_oof[te] = m.predict_proba(X.iloc[te])[:, 1]
    folds_df = _per_fold(y, p_oof, folds)
    return {
        "model": label,
        "brier_mean": folds_df["brier"].mean(),
        "brier_std": folds_df["brier"].std(ddof=1),
        "log_loss_mean": folds_df["log_loss"].mean(),
        "log_loss_std": folds_df["log_loss"].std(ddof=1),
        "auc_mean": folds_df["auc"].mean(),
        "auc_std": folds_df["auc"].std(ddof=1),
    }


def main():
    df = load_modeling_frame().reset_index(drop=True)
    y = df["firms_hit"].astype(int).values
    folds = list(StratifiedKFold(n_splits=5, shuffle=True, random_state=RNG).split(df, y))

    print("Fitting v1 GBM with full feature set (includes hours_since_overpass)...")
    res_full = _evaluate("gbm_v1_full", NUMERIC_FULL, df, y, folds)

    print("Fitting v1 GBM with hours_since_overpass dropped...")
    res_ablated = _evaluate("gbm_v1_no_overpass", NUMERIC_ABLATED, df, y, folds)

    # Pull size-class baseline from the existing parquet for the head-to-head.
    base = pd.read_parquet(PROCESSED / "model_metrics_with_uncertainty.parquet")
    base_size_class = base[base["model"] == "size_class"].iloc[0].to_dict()

    fmt = lambda m, s: f"{m:.4f} ± {s:.4f}"
    print()
    print(f"{'model':<28} {'Brier':<22} {'Log-loss':<22} {'AUC':<22}")
    for r in [base_size_class, res_full, res_ablated]:
        name = r["model"]
        print(f"{name:<28} {fmt(r['brier_mean'], r['brier_std']):<22} "
              f"{fmt(r['log_loss_mean'], r['log_loss_std']):<22} "
              f"{fmt(r['auc_mean'], r['auc_std']):<22}")

    # Save the ablation row alongside the existing uncertainty table for future reference.
    out = base.copy()
    out = pd.concat([out, pd.DataFrame([res_ablated])], ignore_index=True).drop_duplicates(
        "model", keep="last"
    )
    out.to_parquet(PROCESSED / "model_metrics_with_uncertainty.parquet", index=False)
    print(f"\nappended ablation row -> {PROCESSED / 'model_metrics_with_uncertainty.parquet'}")


if __name__ == "__main__":
    main()
