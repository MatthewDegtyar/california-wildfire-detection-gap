"""Regenerate the v3 gap surface using a cause-mix-weighted prediction instead
of the hard-coded "Natural" cause used in model_v3.py.

The original implementation set `cause = "Natural"` for every grid cell. Only
~8% of 2020 CA fires are Natural-caused; the most common label is "Missing data
/ not specified / undetermined" (56%), followed by Arson, Equipment, Natural,
Debris, etc. Reading the map as "marginal aerial value across CA" while
silently conditioning on Natural cause produces a Lightning-country-biased
spatial story (Klamath / Sierra hot-zones light up partly because the model
extrapolates from Natural-cause training fires).

Fix: predict on the grid once per cause, then average across causes weighted
by the 2020 cause distribution. The output is the mixture predicted gap.
"""

from __future__ import annotations

import pickle

import numpy as np
import pandas as pd

from src.config import PROCESSED


SCENARIOS = {
    "1ac_peakseason_morning":   dict(fire_size=1.0,   doy=197, disc_hour=11.0),
    "1ac_peakseason_afternoon": dict(fire_size=1.0,   doy=197, disc_hour=15.0),
    "100ac_peakseason_morning": dict(fire_size=100.0, doy=197, disc_hour=11.0),
}


def main():
    with (PROCESSED / "final_model_v3.pkl").open("rb") as f:
        model = pickle.load(f)

    fpa = pd.read_parquet(PROCESSED / "fpafod_ca_2020_with_fuel.parquet")
    cause_dist = (
        fpa["NWCG_GENERAL_CAUSE"].fillna("Missing data/not specified/undetermined")
           .value_counts(normalize=True)
    )
    print("2020 CA cause distribution (used as mixture weights):")
    print((cause_dist * 100).round(1).to_string())
    print()

    grid = pd.read_parquet(PROCESSED / "grid_terrain_fuel.parquet")

    out_frames = []
    for name, scen in SCENARIOS.items():
        doy = scen["doy"]
        sd = np.sin(2 * np.pi * doy / 366); cd = np.cos(2 * np.pi * doy / 366)
        dh = scen["disc_hour"]
        hsh = min((dh - h) % 24 for h in (2.0, 14.0))

        # Run the model once per cause; weight predictions by the cause-mix.
        n_cells = len(grid)
        p_hit_mix = np.zeros(n_cells)
        for cause_label, weight in cause_dist.items():
            X = pd.DataFrame({
                "log_size": np.log10(scen["fire_size"]),
                "LATITUDE": grid["lat"], "LONGITUDE": grid["lon"],
                "sin_doy": sd, "cos_doy": cd,
                "disc_hour": dh, "hours_since_overpass": hsh,
                "elevation_m": grid["elevation_m"],
                "slope_deg": grid["slope_deg"], "aspect_sin": grid["aspect_sin"],
                "aspect_cos": grid["aspect_cos"], "tpi_m": grid["tpi_m"],
                "cause": cause_label, "fuel_group": grid["fuel_group"].fillna("Unknown"),
            })
            p_hit_mix += weight * model.predict_proba(X)[:, 1]

        gap = 1.0 - p_hit_mix
        out = grid[["lat", "lon"]].rename(columns={"lat": "LATITUDE", "lon": "LONGITUDE"}).copy()
        out["scenario"] = name
        out["p_firms_hit"] = p_hit_mix
        out["marginal_aerial_value"] = gap
        out_frames.append(out)
        print(f"{name}: median gap = {np.median(gap):.3f}  p90 = {np.quantile(gap, 0.9):.3f}")

    pd.concat(out_frames, ignore_index=True).to_parquet(
        PROCESSED / "gap_surface_v3_unbiased.parquet", index=False
    )
    print(f"\nwrote -> {PROCESSED / 'gap_surface_v3_unbiased.parquet'}")


if __name__ == "__main__":
    main()
