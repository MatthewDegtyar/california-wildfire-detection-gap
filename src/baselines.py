"""Naive baselines for predicting FIRMS-hit.

The point: any modeled result has to beat these. start.md is explicit on this —
"A result with no baseline is not a result."

Baselines (all on the same 5-fold stratified split):
  - constant_yes:       always predict 1
  - constant_no:        always predict 0
  - base_rate:          predict overall train-set rate
  - size_class:         predict the train-set rate of the fire's NWCG size class
  - size_class_x_lat:   train-set rate stratified by size class + 1-degree lat band
"""

from __future__ import annotations

import numpy as np
import pandas as pd
from sklearn.metrics import brier_score_loss, log_loss, roc_auc_score
from sklearn.model_selection import StratifiedKFold

from src.config import PROCESSED
from src.features import load_modeling_frame

RNG = 0


def _safe_auc(y, p):
    if len(np.unique(y)) < 2:
        return np.nan
    return roc_auc_score(y, p)


def _eval(name, y, p):
    return {
        "model": name,
        "brier": brier_score_loss(y, p),
        "log_loss": log_loss(y, np.clip(p, 1e-6, 1 - 1e-6)),
        "auc": _safe_auc(y, p),
        "mean_pred": float(np.mean(p)),
        "mean_actual": float(np.mean(y)),
    }


def main():
    df = load_modeling_frame().reset_index(drop=True)
    y = df["firms_hit"].astype(int).values

    skf = StratifiedKFold(n_splits=5, shuffle=True, random_state=RNG)
    folds = list(skf.split(df, y))

    # collect out-of-fold predictions for each baseline
    p_const_yes = np.ones(len(df))
    p_const_no = np.zeros(len(df))
    p_base = np.zeros(len(df))
    p_size = np.zeros(len(df))
    p_size_lat = np.zeros(len(df))

    df["lat_band"] = (df["LATITUDE"] // 1).astype(int)

    for tr, te in folds:
        train_rate = y[tr].mean()
        p_base[te] = train_rate

        # size-class lookup
        rate_by_sc = (
            pd.Series(y[tr]).groupby(df.loc[tr, "FIRE_SIZE_CLASS"].values).mean()
        )
        p_size[te] = df.loc[te, "FIRE_SIZE_CLASS"].map(rate_by_sc).fillna(train_rate).values

        # size-class x lat-band lookup with size-class fallback
        rate_by_key = (
            pd.DataFrame({
                "sc": df.loc[tr, "FIRE_SIZE_CLASS"].values,
                "lb": df.loc[tr, "lat_band"].values,
                "y": y[tr],
            })
            .groupby(["sc", "lb"])["y"].mean()
        )
        keys_te = pd.MultiIndex.from_arrays(
            [df.loc[te, "FIRE_SIZE_CLASS"].values, df.loc[te, "lat_band"].values],
            names=["sc", "lb"],
        )
        p1 = rate_by_key.reindex(keys_te).values
        fallback = df.loc[te, "FIRE_SIZE_CLASS"].map(rate_by_sc).fillna(train_rate).values
        p1 = np.where(np.isnan(p1), fallback, p1)
        p_size_lat[te] = p1

    rows = [
        _eval("constant_yes", y, p_const_yes),
        _eval("constant_no", y, p_const_no),
        _eval("base_rate", y, p_base),
        _eval("size_class", y, p_size),
        _eval("size_class_x_lat", y, p_size_lat),
    ]
    res = pd.DataFrame(rows)
    print(res.to_string(index=False, float_format=lambda x: f"{x:.4f}"))

    # persist baseline predictions for downstream plots
    df_out = df[["FOD_ID", "FIRE_SIZE", "FIRE_SIZE_CLASS", "LATITUDE", "LONGITUDE",
                 "firms_hit"]].copy()
    df_out["p_base_rate"] = p_base
    df_out["p_size_class"] = p_size
    df_out["p_size_class_x_lat"] = p_size_lat
    df_out.to_parquet(PROCESSED / "baselines_oof.parquet", index=False)
    res.to_parquet(PROCESSED / "baseline_metrics.parquet", index=False)
    print(f"\nwrote -> {PROCESSED / 'baselines_oof.parquet'} and baseline_metrics.parquet")


if __name__ == "__main__":
    main()
