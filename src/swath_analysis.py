"""FIRMS swath-edge stratification.

VIIRS Suomi-NPP scans across a ~3,000 km swath. Pixels near nadir are ~375 m;
pixels near the swath edge can be 2-3x larger. FIRMS exposes this as
`scan` and `track` (km), where `pixel_area_km2 ≈ scan * track`. A larger pixel
has a higher false-alarm threshold and worse sub-pixel sensitivity, so
edge-of-swath detections should be later and worse.

We split FIRMS into three swath buckets, then:
  1. show the overall distribution of pixel size in the season
  2. re-run the v1 hit-rate (centroid+radius) using only nadir / mid / edge pixels
     and see how the hit rate by size class changes
"""

from __future__ import annotations

from datetime import timedelta

import numpy as np
import pandas as pd

from src.config import PROCESSED

EARTH_R_KM = 6371.0088
RADIUS_KM = 3.0
PRE_DAYS = 1
MAX_WINDOW_DAYS = 14
POST_DAYS_NO_CONT = 3


def haversine_km(lat1, lon1, lat2, lon2):
    lat1 = np.radians(lat1); lon1 = np.radians(lon1)
    lat2 = np.radians(lat2); lon2 = np.radians(lon2)
    dlat = lat2 - lat1; dlon = lon2 - lon1
    a = np.sin(dlat / 2) ** 2 + np.cos(lat1) * np.cos(lat2) * np.sin(dlon / 2) ** 2
    return 2 * EARTH_R_KM * np.arcsin(np.sqrt(a))


def hit_rate(firms_subset, fpa):
    by_day = {d: g for d, g in firms_subset.groupby("acq_date_dt")}
    hit = np.zeros(len(fpa), dtype=bool)
    for i, row in enumerate(fpa.itertuples(index=False)):
        lat, lon = row.LATITUDE, row.LONGITUDE
        disc = row.DISCOVERY_DATE
        if pd.isna(lat) or pd.isna(lon) or pd.isna(disc):
            continue
        cont = pd.to_datetime(getattr(row, "CONT_DATE", None), errors="coerce")
        end_day = (cont if pd.notna(cont) else disc + timedelta(days=POST_DAYS_NO_CONT))
        end_day = min(end_day, disc + timedelta(days=MAX_WINDOW_DAYS))
        start_day = disc - timedelta(days=PRE_DAYS)

        lat_pad = RADIUS_KM / 111.0
        lon_pad = RADIUS_KM / (111.0 * max(np.cos(np.radians(lat)), 0.1))
        day = start_day
        while day <= end_day:
            g = by_day.get(day)
            day = day + timedelta(days=1)
            if g is None or g.empty:
                continue
            m = (
                (g["latitude"] >= lat - lat_pad)
                & (g["latitude"] <= lat + lat_pad)
                & (g["longitude"] >= lon - lon_pad)
                & (g["longitude"] <= lon + lon_pad)
            )
            cand = g.loc[m]
            if cand.empty:
                continue
            d = haversine_km(lat, lon, cand["latitude"].values, cand["longitude"].values)
            if (d <= RADIUS_KM).any():
                hit[i] = True
                break
    return hit


def main():
    firms = pd.read_parquet(PROCESSED / "firms_ca_2020.parquet")
    firms["pixel_area_km2"] = firms["scan"] * firms["track"]
    firms["acq_date_dt"] = pd.to_datetime(firms["acq_date"], errors="coerce")

    fpa = pd.read_parquet(PROCESSED / "fpafod_ca_2020.parquet")
    fpa["DISCOVERY_DATE"] = pd.to_datetime(fpa["DISCOVERY_DATE"], errors="coerce")

    # Pixel-area buckets — split at quantiles of the actual distribution
    q33, q66 = firms["pixel_area_km2"].quantile([0.33, 0.66]).values
    print(f"pixel-area quantiles (km²): p33={q33:.3f}  p66={q66:.3f}  p100={firms['pixel_area_km2'].max():.3f}")
    firms["swath_bucket"] = pd.cut(
        firms["pixel_area_km2"],
        bins=[-np.inf, q33, q66, np.inf],
        labels=["nadir", "mid", "edge"],
    )

    print("\nbucket counts:")
    print(firms["swath_bucket"].value_counts().sort_index())

    # Hit rate by swath bucket (re-run the v1 envelope but restricted to one bucket)
    out_rows = []
    for label in ["nadir", "mid", "edge"]:
        sub = firms[firms["swath_bucket"] == label]
        print(f"\nrunning hit-rate calc for swath={label} ({len(sub):,} pixels) ...")
        hit = hit_rate(sub, fpa)
        # by size bucket
        size_bins = [0, 10, 100, 1000, 10_000, 1_500_000]
        size_labels = ["<10", "10-100", "100-1k", "1k-10k", "10k+"]
        sb = pd.cut(fpa["FIRE_SIZE"], bins=size_bins, labels=size_labels, include_lowest=True, right=False)
        for slab in size_labels:
            mask = (sb == slab).values
            if mask.sum() == 0:
                continue
            out_rows.append({
                "swath_bucket": label,
                "size_bucket": slab,
                "n": int(mask.sum()),
                "hits": int(hit[mask].sum()),
                "hit_rate": float(hit[mask].mean()),
            })

    summary = pd.DataFrame(out_rows)
    pivot_rate = summary.pivot(index="size_bucket", columns="swath_bucket", values="hit_rate")
    pivot_n = summary.pivot(index="size_bucket", columns="swath_bucket", values="hits")
    print("\nhit rate by size × swath bucket:")
    print(pivot_rate.to_string(float_format=lambda x: f"{x:.3f}"))
    print("\nhit count (number of fires with at least one matching pixel of this swath class):")
    print(pivot_n.to_string())

    summary.to_parquet(PROCESSED / "swath_hit_summary.parquet", index=False)
    print(f"\nwrote -> {PROCESSED / 'swath_hit_summary.parquet'}")


if __name__ == "__main__":
    main()
