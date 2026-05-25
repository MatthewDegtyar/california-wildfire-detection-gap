"""Compute 5-fold uncertainty bands (mean +- std) for every baseline and model.

We rebuild the same 5-fold StratifiedKFold split used by baselines.py / model.py
/ model_v2.py / model_v3.py (same RNG=0), then compute Brier / log-loss / AUC
*within each test fold* on the saved OOF predictions. The pooled-OOF metric
in the existing tables is the dataset-level number; the per-fold mean +- std
quantifies sampling noise across the 5 held-out splits.

Output: data/processed/model_metrics_with_uncertainty.parquet
"""

from __future__ import annotations

import numpy as np
import pandas as pd
from sklearn.metrics import brier_score_loss, log_loss, roc_auc_score
from sklearn.model_selection import StratifiedKFold

from src.config import PROCESSED
from src.features import build

RNG = 0


def _fold_split(df: pd.DataFrame, y) -> list[tuple]:
    skf = StratifiedKFold(n_splits=5, shuffle=True, random_state=RNG)
    return list(skf.split(df, y))


def _per_fold(y_true, p, folds):
    rows = []
    for k, (_, te) in enumerate(folds):
        yt = y_true[te]
        pt = np.clip(p[te], 1e-6, 1 - 1e-6)
        if len(np.unique(yt)) < 2:
            auc = np.nan
        else:
            auc = roc_auc_score(yt, pt)
        rows.append({
            "fold": k,
            "brier": brier_score_loss(yt, pt),
            "log_loss": log_loss(yt, pt),
            "auc": auc,
        })
    return pd.DataFrame(rows)


def _summarize(name, fold_df):
    return {
        "model": name,
        "brier_mean": fold_df["brier"].mean(),
        "brier_std": fold_df["brier"].std(ddof=1),
        "log_loss_mean": fold_df["log_loss"].mean(),
        "log_loss_std": fold_df["log_loss"].std(ddof=1),
        "auc_mean": fold_df["auc"].mean(),
        "auc_std": fold_df["auc"].std(ddof=1),
    }


def main():
    # --- baselines (constant_no, base_rate, size_class, size_class_x_lat) ---
    bdf = pd.read_parquet(PROCESSED / "baselines_oof.parquet").reset_index(drop=True)
    matched = pd.read_parquet(PROCESSED / "fpafod_with_firms_match_v1.parquet").reset_index(drop=True)
    # baselines.py used the modeling frame from features.build, dropping rows
    # without FIRE_SIZE / lat / lon. Recreate that for fold reproducibility.
    df_full = build(matched).reset_index(drop=True)
    y = df_full["firms_hit"].astype(int).values
    folds = _fold_split(df_full, y)
    n = len(df_full)

    # Reconcile baselines_oof to the same row order (FOD_ID join)
    base_aligned = df_full[["FOD_ID"]].merge(
        bdf[["FOD_ID", "p_base_rate", "p_size_class", "p_size_class_x_lat"]],
        on="FOD_ID", how="left",
    )

    rows = []
    rows.append(_summarize("constant_no", _per_fold(y, np.zeros(n), folds)))
    rows.append(_summarize("constant_yes", _per_fold(y, np.ones(n), folds)))
    rows.append(_summarize("base_rate", _per_fold(y, base_aligned["p_base_rate"].values, folds)))
    rows.append(_summarize("size_class", _per_fold(y, base_aligned["p_size_class"].values, folds)))
    rows.append(_summarize("size_class_x_lat", _per_fold(y, base_aligned["p_size_class_x_lat"].values, folds)))

    # --- model v1 (logreg + gbm), v2 (gbm + elevation), v3 (gbm + terrain + fuel) ---
    for src, names in [
        ("model_oof.parquet", [("p_logreg", "logreg_calibrated"),
                                ("p_gbm", "gbm_calibrated")]),
        ("model_v2_oof.parquet", [("p_gbm_v2", "gbm_v2_with_elevation")]),
        ("model_v3_oof.parquet", [("p_gbm_v3", "gbm_v3_elev_terrain_fuel")]),
    ]:
        oof = pd.read_parquet(PROCESSED / src)
        aligned = df_full[["FOD_ID"]].merge(oof, on="FOD_ID", how="left")
        for col, label in names:
            rows.append(_summarize(label, _per_fold(y, aligned[col].values, folds)))

    res = pd.DataFrame(rows)
    res.to_parquet(PROCESSED / "model_metrics_with_uncertainty.parquet", index=False)

    print("Per-fold metrics (mean +- std across 5 stratified folds):\n")
    fmt = lambda m, s: f"{m:.4f} ± {s:.4f}"
    print(f"{'model':<28} {'Brier':<18} {'Log-loss':<18} {'AUC':<18}")
    for _, r in res.iterrows():
        print(f"{r['model']:<28} {fmt(r.brier_mean, r.brier_std):<18} "
              f"{fmt(r.log_loss_mean, r.log_loss_std):<18} "
              f"{fmt(r.auc_mean, r.auc_std):<18}")


if __name__ == "__main__":
    main()
