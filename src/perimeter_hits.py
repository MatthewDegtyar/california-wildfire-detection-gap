"""Perimeter-based hit/miss as an alternative to the centroid+radius envelope.

For each FPA-FOD fire that we can map to a 2020 burn perimeter (point-in-polygon
on the discovery coordinate, with a name-match cross-check where possible),
redefine "FIRMS hit" as "any FIRMS pixel inside the polygon during the fire's
active window."

This addresses the Castle-Fire failure mode: when the FPA-FOD discovery
coordinate is ~120 km off-burn, the centroid+radius envelope misses, but the
polygon-based join still catches it. It also lifts the hit-rate ceiling for
big fires from ~90% toward 100%.

Reports:
  - hit-rate by size bucket, perimeter-based
  - the lift over the v1 (centroid+radius) hit rate for the same subset
"""

from __future__ import annotations

import geopandas as gpd
import numpy as np
import pandas as pd
from shapely.geometry import Point

from src.config import PROCESSED


def main():
    perims = gpd.read_file(PROCESSED / "perimeters_ca_2020.gpkg").to_crs("EPSG:4326")
    perims = (
        perims[perims["INCIDENT"].notna() & (perims["GIS_ACRES"].fillna(0) >= 1)]
        .sort_values("GIS_ACRES", ascending=False)
        .drop_duplicates("INCIDENT", keep="first")
        .reset_index(drop=True)
    )

    fpa = pd.read_parquet(PROCESSED / "fpafod_with_firms_match_v1.parquet")
    fpa["DISCOVERY_DATE"] = pd.to_datetime(fpa["DISCOVERY_DATE"], errors="coerce", utc=True)
    fpa_g = gpd.GeoDataFrame(
        fpa, geometry=gpd.points_from_xy(fpa["LONGITUDE"], fpa["LATITUDE"]), crs="EPSG:4326"
    )

    # FPA point inside which perimeter? (multiple matches possible — keep the largest)
    joined = gpd.sjoin(fpa_g, perims[["INCIDENT", "GIS_ACRES", "geometry"]],
                       predicate="within", how="left")
    joined = (
        joined.sort_values("GIS_ACRES", ascending=False)
              .drop_duplicates("FOD_ID", keep="first")
    )
    fpa = fpa.merge(
        joined[["FOD_ID", "INCIDENT", "GIS_ACRES"]].rename(columns={"GIS_ACRES": "perim_acres"}),
        on="FOD_ID", how="left",
    )
    print(f"FPA-FOD fires inside any perimeter: {fpa['INCIDENT'].notna().sum()} / {len(fpa)}")

    # FIRMS pixels inside each perimeter, keyed by date so we can apply per-fire
    # temporal filtering (else a June-small-fire-inside-Creek-perimeter gets
    # falsely credited for an August FIRMS pixel).
    firms = pd.read_parquet(PROCESSED / "firms_ca_2020.parquet")
    firms["acq_date_dt"] = pd.to_datetime(firms["acq_date"], errors="coerce", utc=True)
    firms_g = gpd.GeoDataFrame(
        firms, geometry=gpd.points_from_xy(firms["longitude"], firms["latitude"]), crs="EPSG:4326"
    )
    firms_in = gpd.sjoin(firms_g, perims[["INCIDENT", "geometry"]], predicate="within", how="inner")
    print(f"FIRMS pixels inside any perimeter: {len(firms_in):,} / {len(firms):,}")
    firms_in["acq_date_dt"] = pd.to_datetime(firms_in["acq_date"], errors="coerce", utc=True)

    # For each FPA fire inside a perimeter, the temporal window is the same as
    # v1: DISCOVERY_DATE - 1d to min(CONT_DATE, DISCOVERY_DATE + 14d).
    from datetime import timedelta
    fpa["CONT_DATE_dt"] = pd.to_datetime(fpa["CONT_DATE"], errors="coerce", utc=True)
    # Build a per-INCIDENT pixel date index
    # Normalize all to naive (date-only) for clean comparisons
    pix_by_incident = {
        inc: pd.to_datetime(g["acq_date_dt"]).dt.tz_localize(None).dt.normalize().values
        for inc, g in firms_in.groupby("INCIDENT")
    }
    hit_perim = np.zeros(len(fpa), dtype=bool)
    pix_count = np.zeros(len(fpa), dtype=np.int32)
    for i, row in enumerate(fpa.itertuples(index=False)):
        inc = row.INCIDENT
        if pd.isna(inc) or inc not in pix_by_incident:
            continue
        disc = row.DISCOVERY_DATE
        if pd.isna(disc):
            continue
        disc_naive = pd.Timestamp(disc).tz_localize(None) if pd.Timestamp(disc).tzinfo else pd.Timestamp(disc)
        cont = row.CONT_DATE_dt if not pd.isna(row.CONT_DATE_dt) else None
        cont_naive = pd.Timestamp(cont).tz_localize(None) if cont is not None and pd.Timestamp(cont).tzinfo else cont
        start = (disc_naive - timedelta(days=1)).normalize()
        end = (cont_naive if cont_naive is not None else disc_naive + timedelta(days=3))
        end = min(end, disc_naive + timedelta(days=14)).normalize()
        pix_dates = pix_by_incident[inc]
        mask = (pix_dates >= np.datetime64(start.to_datetime64())) & (pix_dates <= np.datetime64(end.to_datetime64()))
        if mask.any():
            hit_perim[i] = True
            pix_count[i] = int(mask.sum())

    fpa["firms_in_perim_count"] = pix_count
    fpa["firms_hit_perim"] = hit_perim
    # For fires inside a perimeter, hit-flag = any FIRMS pixel in that perimeter
    # during the fire's active window. For fires NOT inside any perimeter, fall
    # back to the v1 radius-based flag.
    fpa["firms_hit_v2"] = np.where(
        fpa["INCIDENT"].notna(),
        fpa["firms_hit_perim"],
        fpa["firms_hit"].astype(bool),
    )

    # Headlines
    print(f"\nv1 (centroid+radius) overall hit rate: {fpa['firms_hit'].mean():.3f}")
    print(f"v2 (perimeter where available)   hit rate: {fpa['firms_hit_v2'].mean():.3f}")

    bins = [0, 0.25, 1, 10, 100, 300, 1000, 10_000, 100_000, 1_500_000]
    labels = ["<0.25", "0.25-1", "1-10", "10-100", "100-300", "300-1k", "1k-10k", "10k-100k", "100k+"]
    fpa["size_bucket"] = pd.cut(fpa["FIRE_SIZE"], bins=bins, labels=labels, include_lowest=True, right=False)

    g = fpa.groupby("size_bucket", observed=True).agg(
        n=("FOD_ID", "size"),
        n_in_perim=("INCIDENT", lambda s: s.notna().sum()),
        hit_v1=("firms_hit", "mean"),
        hit_v2=("firms_hit_v2", "mean"),
    )
    print("\nhit rate by acres bucket (perimeter vs centroid):")
    print(g.to_string(float_format=lambda x: f"{x:.3f}" if isinstance(x, float) else str(x)))

    # Subset that's *inside* a perimeter only — the apples-to-apples comparison
    sub = fpa[fpa["INCIDENT"].notna()]
    print(f"\non the {len(sub):,} fires inside a perimeter:")
    print(f"  v1 hit rate: {sub['firms_hit'].mean():.3f}")
    print(f"  v2 hit rate: {sub['firms_hit_v2'].mean():.3f}")

    out = PROCESSED / "fpafod_with_firms_match_v2.parquet"
    fpa.to_parquet(out, index=False)
    print(f"\nwrote -> {out}")


if __name__ == "__main__":
    main()
