"""Predict the FIRMS detection gap surface over California.

Walks a 0.1-degree grid covering the CA bounding box. For each cell, asks the
trained model: "If a small fire (default 1 acre) started here at peak-season
mid-day, what is P(FIRMS detects it)?"  The marginal aerial value at that cell
is 1 - P(detect): the higher, the more value drones add by closing the gap.

Scenarios produced:
  - "1ac_peakseason_morning"   — 1-acre fire, July 15, 11:00 local
  - "1ac_peakseason_afternoon" — 1-acre fire, July 15, 15:00 local (post-overpass)
  - "100ac_peakseason_morning" — 100-acre fire (where FIRMS detection improves)
"""

from __future__ import annotations

import pickle

import numpy as np
import pandas as pd

from src.config import CA_BBOX, PROCESSED


GRID_DEG = 0.1


SCENARIOS = {
    "1ac_peakseason_morning":   dict(fire_size=1.0,   doy=197, disc_hour=11.0),
    "1ac_peakseason_afternoon": dict(fire_size=1.0,   doy=197, disc_hour=15.0),
    "100ac_peakseason_morning": dict(fire_size=100.0, doy=197, disc_hour=11.0),
}


def _build_grid_frame(scenario: dict) -> pd.DataFrame:
    w, s, e, n = CA_BBOX
    lons = np.arange(w, e + 1e-9, GRID_DEG)
    lats = np.arange(s, n + 1e-9, GRID_DEG)
    lon_g, lat_g = np.meshgrid(lons, lats)
    flat_lat = lat_g.ravel()
    flat_lon = lon_g.ravel()

    doy = scenario["doy"]
    sin_doy = np.sin(2 * np.pi * doy / 366)
    cos_doy = np.cos(2 * np.pi * doy / 366)

    disc_hour = scenario["disc_hour"]
    candidates = [(disc_hour - h) % 24 for h in (2.0, 14.0)]
    hours_since = min(candidates)

    df = pd.DataFrame({
        "log_size": np.log10(scenario["fire_size"]),
        "LATITUDE": flat_lat,
        "LONGITUDE": flat_lon,
        "sin_doy": sin_doy,
        "cos_doy": cos_doy,
        "disc_hour": disc_hour,
        "hours_since_overpass": hours_since,
        "cause": "Natural",   # assume lightning-like; "cause" effect is weak in the model
    })
    return df


def main():
    with (PROCESSED / "final_model.pkl").open("rb") as f:
        model = pickle.load(f)

    out_frames = []
    for name, scen in SCENARIOS.items():
        X = _build_grid_frame(scen)
        p_hit = model.predict_proba(X)[:, 1]
        marginal_value = 1.0 - p_hit
        X = X.assign(scenario=name, p_firms_hit=p_hit, marginal_aerial_value=marginal_value)
        out_frames.append(X)
        print(f"{name}: mean P(hit)={p_hit.mean():.3f}  mean gap={marginal_value.mean():.3f}  "
              f"min gap={marginal_value.min():.3f}  max gap={marginal_value.max():.3f}")

    grid = pd.concat(out_frames, ignore_index=True)
    out = PROCESSED / "gap_surface.parquet"
    grid.to_parquet(out, index=False)
    print(f"\nwrote {len(grid):,} grid cells -> {out}")


if __name__ == "__main__":
    main()
