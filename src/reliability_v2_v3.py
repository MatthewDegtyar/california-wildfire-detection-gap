"""Extend reliability-bin computation to v2 (elevation) and v3 (terrain+fuel)
models, plus refresh v1 numbers from the same code path.

The original model.py wrote reliability bins only for v1. The nominal model in
the memo is v2; the v3 row appears in the table. Calibration must be reported
for the model the reader sees.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from src.config import PROCESSED


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


def main():
    # v1 OOF predictions
    v1 = pd.read_parquet(PROCESSED / "model_oof.parquet")
    y1 = v1["firms_hit"].astype(int).values
    rel_lr = reliability_bins(y1, v1["p_logreg"].values).assign(model="logreg_calibrated")
    rel_gbm = reliability_bins(y1, v1["p_gbm"].values).assign(model="gbm_calibrated")

    # v2 OOF predictions
    v2 = pd.read_parquet(PROCESSED / "model_v2_oof.parquet")
    rel_gbm_v2 = reliability_bins(
        v2["firms_hit"].astype(int).values,
        v2["p_gbm_v2"].values,
    ).assign(model="gbm_v2_with_elevation")

    # v3 OOF predictions
    v3 = pd.read_parquet(PROCESSED / "model_v3_oof.parquet")
    rel_gbm_v3 = reliability_bins(
        v3["firms_hit"].astype(int).values,
        v3["p_gbm_v3"].values,
    ).assign(model="gbm_v3_elev_terrain_fuel")

    out = pd.concat([rel_lr, rel_gbm, rel_gbm_v2, rel_gbm_v3], ignore_index=True)
    out.to_parquet(PROCESSED / "model_reliability.parquet", index=False)

    for name in ["logreg_calibrated", "gbm_calibrated", "gbm_v2_with_elevation", "gbm_v3_elev_terrain_fuel"]:
        print(f"\n{name}:")
        sub = out[out["model"] == name][["bin_low", "bin_high", "n", "mean_pred", "mean_actual"]]
        sub = sub.assign(diff_pp=(sub["mean_actual"] - sub["mean_pred"]) * 100)
        print(sub.to_string(index=False, float_format=lambda x: f"{x:.3f}"))


if __name__ == "__main__":
    main()
