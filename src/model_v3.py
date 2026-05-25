"""Detection-gap model v3 — adds terrain derivatives (slope/aspect/TPI) and
LANDFIRE FBFM40 fuel group on top of the v2 elevation feature.

Same calibrated GBM pipeline. Compares to v2 head-to-head.
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

from src.config import PROCESSED
from src.features import build

RNG = 0

NUMERIC_V3 = ["log_size", "LATITUDE", "LONGITUDE", "sin_doy", "cos_doy",
              "disc_hour", "hours_since_overpass",
              "elevation_m", "slope_deg", "aspect_sin", "aspect_cos", "tpi_m"]
CATEGORICAL_V3 = ["cause", "fuel_group"]


def _gbm() -> Pipeline:
    return Pipeline([
        ("pre", ColumnTransformer([
            ("num", "passthrough", NUMERIC_V3),
            ("cat", OneHotEncoder(handle_unknown="ignore", min_frequency=10, sparse_output=False), CATEGORICAL_V3),
        ])),
        ("clf", HistGradientBoostingClassifier(
            max_iter=400, learning_rate=0.04, max_depth=5,
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


def _load_frame() -> pd.DataFrame:
    matched = pd.read_parquet(PROCESSED / "fpafod_with_firms_match_v1.parquet")
    fuel = pd.read_parquet(PROCESSED / "fpafod_ca_2020_with_fuel.parquet")[
        ["FOD_ID", "elevation_m", "slope_deg", "aspect_sin", "aspect_cos", "tpi_m",
         "fbfm40", "fuel_group"]
    ]
    df = matched.merge(fuel, on="FOD_ID", how="left")
    df = build(df)
    return df


def main():
    df = _load_frame().reset_index(drop=True)
    y = df["firms_hit"].astype(int).values
    X = df[NUMERIC_V3 + CATEGORICAL_V3]
    print(f"rows: {len(df)}  hit rate: {y.mean():.3f}")
    print(f"slope_deg: median={df['slope_deg'].median():.1f}  q90={df['slope_deg'].quantile(0.9):.1f}")
    print(f"tpi_m: median={df['tpi_m'].median():.1f}  IQR=[{df['tpi_m'].quantile(0.25):.1f}, {df['tpi_m'].quantile(0.75):.1f}]")
    print(f"fuel_group distribution:\n{df['fuel_group'].value_counts()}")

    skf = StratifiedKFold(n_splits=5, shuffle=True, random_state=RNG)
    p_oof = np.zeros(len(y))
    for tr, te in skf.split(X, y):
        m = CalibratedClassifierCV(_gbm(), method="isotonic", cv=5)
        m.fit(X.iloc[tr], y[tr])
        p_oof[te] = m.predict_proba(X.iloc[te])[:, 1]

    res_v3 = _eval("gbm_v3_elev_terrain_fuel", y, p_oof)
    print("\nv3 metrics (OOF):")
    print(pd.DataFrame([res_v3]).to_string(index=False, float_format=lambda x: f"{x:.4f}"))

    v2 = pd.read_parquet(PROCESSED / "model_metrics_v2.parquet")
    comp = pd.concat([v2, pd.DataFrame([res_v3])], ignore_index=True)
    print("\nfull comparison:")
    print(comp.to_string(index=False, float_format=lambda x: f"{x:.4f}"))
    comp.to_parquet(PROCESSED / "model_metrics_v3.parquet", index=False)

    out = df[["FOD_ID", "FIRE_SIZE", "FIRE_SIZE_CLASS", "LATITUDE", "LONGITUDE",
              "elevation_m", "slope_deg", "fuel_group", "firms_hit"]].copy()
    out["p_gbm_v3"] = p_oof
    out.to_parquet(PROCESSED / "model_v3_oof.parquet", index=False)

    # Final model on all data
    print("\nfitting final v3 model ...")
    final = CalibratedClassifierCV(_gbm(), method="isotonic", cv=5)
    final.fit(X, y)
    with (PROCESSED / "final_model_v3.pkl").open("wb") as f:
        pickle.dump(final, f)

    # Gap surface prediction over enriched grid
    grid = pd.read_parquet(PROCESSED / "grid_terrain_fuel.parquet")
    SCENARIOS = {
        "1ac_peakseason_morning":   dict(fire_size=1.0,   doy=197, disc_hour=11.0),
        "1ac_peakseason_afternoon": dict(fire_size=1.0,   doy=197, disc_hour=15.0),
        "100ac_peakseason_morning": dict(fire_size=100.0, doy=197, disc_hour=11.0),
    }
    frames = []
    for name, s in SCENARIOS.items():
        doy = s["doy"]
        sd = np.sin(2 * np.pi * doy / 366); cd = np.cos(2 * np.pi * doy / 366)
        dh = s["disc_hour"]; hsh = min((dh - h) % 24 for h in (2.0, 14.0))
        X_grid = pd.DataFrame({
            "log_size": np.log10(s["fire_size"]),
            "LATITUDE": grid["lat"], "LONGITUDE": grid["lon"],
            "sin_doy": sd, "cos_doy": cd,
            "disc_hour": dh, "hours_since_overpass": hsh,
            "elevation_m": grid["elevation_m"],
            "slope_deg": grid["slope_deg"], "aspect_sin": grid["aspect_sin"],
            "aspect_cos": grid["aspect_cos"], "tpi_m": grid["tpi_m"],
            "cause": "Natural", "fuel_group": grid["fuel_group"].fillna("Unknown"),
        })
        p_hit = final.predict_proba(X_grid)[:, 1]
        gap = 1.0 - p_hit
        X_grid = X_grid.assign(scenario=name, p_firms_hit=p_hit, marginal_aerial_value=gap)
        frames.append(X_grid)
        print(f"{name}: median gap={np.median(gap):.3f}  p90={np.quantile(gap, 0.9):.3f}")

    pd.concat(frames, ignore_index=True).to_parquet(PROCESSED / "gap_surface_v3.parquet", index=False)
    print(f"wrote -> {PROCESSED / 'gap_surface_v3.parquet'}")


if __name__ == "__main__":
    main()
