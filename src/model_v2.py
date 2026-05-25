"""Detection-gap model v2 — adds elevation as a feature.

Same calibrated-GBM pipeline as src.model, with an added `elevation_m` feature
sourced from src.fetch_elevation. Compares head-to-head with v1 metrics.

Also re-trains a final model and runs the gap-surface prediction on the
elevation-enriched grid.
"""

from __future__ import annotations

import pickle

import numpy as np
import pandas as pd
from sklearn.calibration import CalibratedClassifierCV
from sklearn.compose import ColumnTransformer
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.metrics import brier_score_loss, log_loss, roc_auc_score
from sklearn.model_selection import StratifiedKFold
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder

from src.config import CA_BBOX, PROCESSED
from src.features import build

RNG = 0

NUMERIC_V2 = ["log_size", "LATITUDE", "LONGITUDE", "sin_doy", "cos_doy",
              "disc_hour", "hours_since_overpass", "elevation_m"]
CATEGORICAL_V2 = ["cause"]


def _gbm_v2() -> Pipeline:
    return Pipeline([
        ("pre", ColumnTransformer([
            ("num", "passthrough", NUMERIC_V2),
            ("cat", OneHotEncoder(handle_unknown="ignore", min_frequency=10, sparse_output=False), CATEGORICAL_V2),
        ])),
        ("clf", HistGradientBoostingClassifier(
            max_iter=300, learning_rate=0.05, max_depth=5,
            l2_regularization=1.0, random_state=RNG,
        )),
    ])


def _eval(name, y, p):
    return {
        "model": name,
        "brier": brier_score_loss(y, p),
        "log_loss": log_loss(y, np.clip(p, 1e-6, 1 - 1e-6)),
        "auc": roc_auc_score(y, p),
        "mean_pred": float(p.mean()),
        "mean_actual": float(y.mean()),
    }


def _load_v2_frame() -> pd.DataFrame:
    # Start from the v1 matched table (the target column is here)
    matched = pd.read_parquet(PROCESSED / "fpafod_with_firms_match_v1.parquet")
    # Join elevation from the enriched FPA table (keyed by FOD_ID)
    elev_tbl = pd.read_parquet(PROCESSED / "fpafod_ca_2020_with_elev.parquet")[["FOD_ID", "elevation_m"]]
    df = matched.merge(elev_tbl, on="FOD_ID", how="left")
    df = build(df)
    return df


def main():
    df = _load_v2_frame().reset_index(drop=True)
    y = df["firms_hit"].astype(int).values
    X = df[NUMERIC_V2 + CATEGORICAL_V2]
    print(f"rows: {len(df)}  hit rate: {y.mean():.3f}")
    print(f"elevation: missing={df['elevation_m'].isna().mean():.1%}  "
          f"median={df['elevation_m'].median():.0f}m  max={df['elevation_m'].max():.0f}m")

    skf = StratifiedKFold(n_splits=5, shuffle=True, random_state=RNG)
    p_oof = np.zeros(len(y))
    for tr, te in skf.split(X, y):
        m = CalibratedClassifierCV(_gbm_v2(), method="isotonic", cv=5)
        m.fit(X.iloc[tr], y[tr])
        p_oof[te] = m.predict_proba(X.iloc[te])[:, 1]

    res_v2 = _eval("gbm_v2_with_elevation", y, p_oof)
    print("\nv2 metrics (OOF):")
    print(pd.DataFrame([res_v2]).to_string(index=False, float_format=lambda x: f"{x:.4f}"))

    # Compare against v1
    v1_metrics = pd.read_parquet(PROCESSED / "model_metrics.parquet")
    comparison = pd.concat([v1_metrics, pd.DataFrame([res_v2])], ignore_index=True)
    print("\nfull comparison:")
    print(comparison.to_string(index=False, float_format=lambda x: f"{x:.4f}"))
    comparison.to_parquet(PROCESSED / "model_metrics_v2.parquet", index=False)

    # Save v2 OOF for plots
    out_oof = df[["FOD_ID", "FIRE_SIZE", "FIRE_SIZE_CLASS", "LATITUDE", "LONGITUDE",
                  "elevation_m", "firms_hit"]].copy()
    out_oof["p_gbm_v2"] = p_oof
    out_oof.to_parquet(PROCESSED / "model_v2_oof.parquet", index=False)

    # Final model fit on all data + new gap surface
    print("\nfitting final v2 model...")
    final = CalibratedClassifierCV(_gbm_v2(), method="isotonic", cv=5)
    final.fit(X, y)
    with (PROCESSED / "final_model_v2.pkl").open("wb") as f:
        pickle.dump(final, f)

    # Predict on the elevation-enriched grid
    grid_elev = pd.read_parquet(PROCESSED / "grid_elev.parquet")
    SCENARIOS = {
        "1ac_peakseason_morning":   dict(fire_size=1.0,   doy=197, disc_hour=11.0),
        "1ac_peakseason_afternoon": dict(fire_size=1.0,   doy=197, disc_hour=15.0),
        "100ac_peakseason_morning": dict(fire_size=100.0, doy=197, disc_hour=11.0),
    }

    out_frames = []
    for name, scen in SCENARIOS.items():
        doy = scen["doy"]
        sin_doy = np.sin(2 * np.pi * doy / 366)
        cos_doy = np.cos(2 * np.pi * doy / 366)
        disc_hour = scen["disc_hour"]
        hours_since = min((disc_hour - h) % 24 for h in (2.0, 14.0))
        X_grid = pd.DataFrame({
            "log_size": np.log10(scen["fire_size"]),
            "LATITUDE": grid_elev["lat"],
            "LONGITUDE": grid_elev["lon"],
            "sin_doy": sin_doy, "cos_doy": cos_doy,
            "disc_hour": disc_hour, "hours_since_overpass": hours_since,
            "elevation_m": grid_elev["elevation_m"],
            "cause": "Natural",
        })
        p_hit = final.predict_proba(X_grid)[:, 1]
        gap = 1.0 - p_hit
        X_grid = X_grid.assign(scenario=name, p_firms_hit=p_hit, marginal_aerial_value=gap)
        out_frames.append(X_grid)
        print(f"{name}: median gap={np.median(gap):.3f}  p90={np.quantile(gap, 0.9):.3f}")

    grid = pd.concat(out_frames, ignore_index=True)
    grid.to_parquet(PROCESSED / "gap_surface_v2.parquet", index=False)
    print(f"wrote -> {PROCESSED / 'gap_surface_v2.parquet'}")


if __name__ == "__main__":
    main()
