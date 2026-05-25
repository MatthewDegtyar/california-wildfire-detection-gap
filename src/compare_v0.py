"""First-cut FIRMS-vs-ground-truth comparison.

For each FPA-FOD CA 2020 fire, look for any FIRMS VIIRS detection within
a spatial radius and temporal window around the fire's discovery date.
Report hit/miss stratified by size class.

This is the v0 — a single fixed radius, fixed window, no terrain or overpass
adjustments. It exists to establish the rough shape of the bias before we
build anything fancier. See start.md: "A result with no baseline is not a
result."
"""

from __future__ import annotations

from datetime import timedelta

import numpy as np
import pandas as pd

from src.config import PROCESSED

# Search envelope around each ground-truth fire
RADIUS_KM = 5.0          # spatial tolerance around (LAT, LON)
PRE_DAYS = 1             # days before discovery to allow (VIIRS may catch it slightly early)
POST_DAYS = 3            # days after discovery (fire may grow before being detected)

EARTH_R_KM = 6371.0088


def haversine_km(lat1, lon1, lat2, lon2):
    lat1 = np.radians(lat1); lon1 = np.radians(lon1)
    lat2 = np.radians(lat2); lon2 = np.radians(lon2)
    dlat = lat2 - lat1; dlon = lon2 - lon1
    a = np.sin(dlat / 2)**2 + np.cos(lat1) * np.cos(lat2) * np.sin(dlon / 2)**2
    return 2 * EARTH_R_KM * np.arcsin(np.sqrt(a))


def main():
    firms = pd.read_parquet(PROCESSED / "firms_ca_2020.parquet")
    fpa = pd.read_parquet(PROCESSED / "fpafod_ca_2020.parquet")

    print(f"FIRMS detections: {len(firms):,}")
    print(f"FPA-FOD CA Jun-Nov 2020: {len(fpa):,}")

    fpa["DISCOVERY_DATE"] = pd.to_datetime(fpa["DISCOVERY_DATE"], errors="coerce")
    firms["acq_date_dt"] = pd.to_datetime(firms["acq_date"], errors="coerce")

    # Bucket FIRMS by date so we only scan the relevant slice per fire
    firms_by_date = {d: g for d, g in firms.groupby("acq_date_dt")}

    hit_distance = np.full(len(fpa), np.nan)
    hit_lag_days = np.full(len(fpa), np.nan)

    for i, row in enumerate(fpa.itertuples(index=False)):
        lat = row.LATITUDE; lon = row.LONGITUDE
        disc = row.DISCOVERY_DATE
        if pd.isna(lat) or pd.isna(lon) or pd.isna(disc):
            continue
        # bound on |dlat| -> 1 deg lat ~ 111 km, so for RADIUS_KM only need ~0.05 deg
        lat_pad = RADIUS_KM / 111.0
        lon_pad = RADIUS_KM / (111.0 * max(np.cos(np.radians(lat)), 0.1))
        best_dist = np.inf
        best_lag = np.nan
        for d_offset in range(-PRE_DAYS, POST_DAYS + 1):
            day = disc + timedelta(days=d_offset)
            g = firms_by_date.get(day)
            if g is None or g.empty:
                continue
            # cheap bbox prefilter
            m = (
                (g["latitude"] >= lat - lat_pad)
                & (g["latitude"] <= lat + lat_pad)
                & (g["longitude"] >= lon - lon_pad)
                & (g["longitude"] <= lon + lon_pad)
            )
            cand = g.loc[m]
            if cand.empty:
                continue
            d_km = haversine_km(lat, lon, cand["latitude"].values, cand["longitude"].values)
            j = int(np.argmin(d_km))
            if d_km[j] < best_dist:
                best_dist = float(d_km[j])
                best_lag = d_offset
        if best_dist <= RADIUS_KM:
            hit_distance[i] = best_dist
            hit_lag_days[i] = best_lag

    fpa = fpa.copy()
    fpa["firms_hit"] = ~np.isnan(hit_distance)
    fpa["firms_hit_dist_km"] = hit_distance
    fpa["firms_hit_lag_days"] = hit_lag_days

    print(f"\noverall hit rate: {fpa['firms_hit'].mean():.1%}  ({fpa['firms_hit'].sum():,} / {len(fpa):,})")

    # NWCG size classes A-G
    summary = (
        fpa.groupby("FIRE_SIZE_CLASS", dropna=False)
           .agg(n=("FOD_ID", "size"),
                hit=("firms_hit", "sum"),
                hit_rate=("firms_hit", "mean"),
                median_acres=("FIRE_SIZE", "median"))
           .sort_index()
    )
    print("\nhit rate by NWCG size class:")
    print(summary.to_string(float_format=lambda x: f"{x:.3f}" if isinstance(x, float) else str(x)))

    # Acres-bin breakdown — finer view
    bins = [0, 0.25, 1, 10, 100, 300, 1000, 10_000, 100_000, 1_500_000]
    labels = ["<0.25", "0.25-1", "1-10", "10-100", "100-300", "300-1k", "1k-10k", "10k-100k", "100k+"]
    fpa["size_bucket"] = pd.cut(fpa["FIRE_SIZE"], bins=bins, labels=labels, include_lowest=True, right=False)
    summary2 = (
        fpa.groupby("size_bucket", observed=True)
           .agg(n=("FOD_ID", "size"),
                hit=("firms_hit", "sum"),
                hit_rate=("firms_hit", "mean"))
    )
    print("\nhit rate by acres bucket:")
    print(summary2.to_string(float_format=lambda x: f"{x:.3f}" if isinstance(x, float) else str(x)))

    out = PROCESSED / "fpafod_with_firms_match_v0.parquet"
    fpa.to_parquet(out, index=False)
    print(f"\nwrote -> {out}")


if __name__ == "__main__":
    main()
