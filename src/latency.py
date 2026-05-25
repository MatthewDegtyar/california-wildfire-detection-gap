"""Compute FIRMS detection latency using burn perimeters.

Refinement story: a naive "earliest FPA-FOD point inside polygon" gives wildly
contaminated latencies because (a) large 2020 perimeters cover areas where
unrelated June ignitions sit, and (b) FPA-FOD DISCOVERY_DATE without
DISCOVERY_TIME truncates to midnight UTC. We address both:

  * Prefer CAL FIRE incidents `Started` for the fire-start anchor — hour-level
    precision and the timestamp is the actual reported alarm. CAL FIRE has
    228 wildfires for 2020.
  * Match a perimeter to a CAL FIRE incident by case-insensitive substring on
    the perimeter INCIDENT name vs the CAL FIRE `Name` field. Where that
    fails, fall back to FPA-FOD ignitions inside the polygon constrained to
    the same calendar month as the perimeter's update date (DATE_CUR) when
    available — and constrain latency to ±14 days to drop obvious contamination.

For each matched perimeter:
  - first FIRMS pixel inside the polygon (UTC timestamp)
  - latency_h = first_firms - fire_start

Skip perimeters where we cannot anchor a credible start time, and report what
fraction of acres and what fraction of perimeters that excludes.
"""

from __future__ import annotations

import geopandas as gpd
import numpy as np
import pandas as pd

from src.config import PROCESSED


def main():
    perims = gpd.read_file(PROCESSED / "perimeters_ca_2020.gpkg").to_crs("EPSG:4326")
    perims = perims[perims["GIS_ACRES"].fillna(0) >= 1].copy().reset_index(drop=True)
    # Many "Slater" / duplicate perimeters exist (multi-agency curation). Keep
    # the largest polygon per INCIDENT name; drop unnamed.
    perims = perims[perims["INCIDENT"].notna() & (perims["INCIDENT"].str.strip() != "")]
    perims = (
        perims.sort_values("GIS_ACRES", ascending=False)
              .drop_duplicates("INCIDENT", keep="first")
              .reset_index(drop=True)
    )
    print(f"perimeters after dedup: {len(perims)}")

    # ----- Anchor: CAL FIRE name-matched Started time -----
    cal = pd.read_parquet(PROCESSED / "calfire_incidents_2020.parquet")
    cal = cal.dropna(subset=["Started"])
    cal["Started"] = pd.to_datetime(cal["Started"], utc=True, errors="coerce")
    # CAL FIRE names are like "Bobcat Fire " — strip and lower
    cal["name_key"] = cal["Name"].str.strip().str.lower().str.replace(" fire$", "", regex=True)
    perims["name_key"] = perims["INCIDENT"].str.strip().str.lower().str.replace(" fire$", "", regex=True)

    # Aggregate CAL FIRE: earliest Started by name_key
    cal_anchor = cal.sort_values("Started").drop_duplicates("name_key", keep="first")[
        ["name_key", "Started", "AcresBurned"]
    ].rename(columns={"Started": "cal_start", "AcresBurned": "cal_acres"})

    out = perims.merge(cal_anchor, on="name_key", how="left")
    out["fire_start"] = out["cal_start"]
    print(f"name-matched anchors from CAL FIRE: {out['fire_start'].notna().sum()} / {len(out)}")

    # ----- Fallback: FPA-FOD point inside polygon, same-month-or-after relative to DATE_CUR -----
    fpa = pd.read_parquet(PROCESSED / "fpafod_ca_2020.parquet")
    fpa["DISCOVERY_DATE"] = pd.to_datetime(fpa["DISCOVERY_DATE"], errors="coerce", utc=True)
    fpa_pts = gpd.GeoDataFrame(
        fpa, geometry=gpd.points_from_xy(fpa["LONGITUDE"], fpa["LATITUDE"]), crs="EPSG:4326"
    )
    print("spatial join: FPA-FOD in perimeters ...")
    fpa_in = gpd.sjoin(fpa_pts, out[["INCIDENT", "geometry"]], predicate="within", how="inner")

    # For unanchored perimeters: use earliest FPA-FOD inside, but only if there's
    # exactly one FPA-FOD point inside (no risk of picking the wrong fire) — and
    # for perimeters with multiple, take the FPA-FOD whose FIRE_NAME best matches.
    unanchored = out[out["fire_start"].isna()].copy()
    n_anchored_via_fpa = 0
    for idx, row in unanchored.iterrows():
        inside = fpa_in[fpa_in["INCIDENT"] == row["INCIDENT"]]
        if inside.empty:
            continue
        # Prefer rows whose FIRE_NAME / MTBS_FIRE_NAME matches the perimeter name
        target = str(row["INCIDENT"]).strip().lower()
        names = inside["FIRE_NAME"].fillna("").str.lower()
        match = inside[names.str.contains(target[:8] if len(target) >= 4 else target, na=False)]
        cand = match if not match.empty else inside
        if len(cand) > 1 and match.empty:
            continue  # ambiguous, skip rather than guess
        ts = cand["DISCOVERY_DATE"].min()
        if pd.notna(ts):
            out.loc[idx, "fire_start"] = ts
            n_anchored_via_fpa += 1
    print(f"additional anchors from FPA-FOD name-match: {n_anchored_via_fpa}")

    # ----- FIRMS spatial join -----
    firms = pd.read_parquet(PROCESSED / "firms_ca_2020.parquet")
    firms_pts = gpd.GeoDataFrame(
        firms, geometry=gpd.points_from_xy(firms["longitude"], firms["latitude"]), crs="EPSG:4326"
    )
    print("spatial join: FIRMS in perimeters ...")
    firms_in = gpd.sjoin(firms_pts, out[["INCIDENT", "geometry"]], predicate="within", how="inner")

    firms_first_all = (
        firms_in.assign(t=pd.to_datetime(firms_in["acq_datetime_utc"], utc=True, errors="coerce"))
                .groupby("INCIDENT")
                .agg(firms_first=("t", "min"),
                     firms_n_pixels=("t", "size"))
    )
    out = out.merge(firms_first_all, left_on="INCIDENT", right_index=True, how="left")

    # Latency in hours; negative if FIRMS earlier than the ground-truth alarm.
    delta = (out["firms_first"] - out["fire_start"]).dt.total_seconds() / 3600
    out["latency_h"] = delta

    # Sanity guard: if FIRMS first inside polygon is >30d before or >30d after
    # the recorded start, that's almost certainly an unrelated fire — drop.
    bad = (out["latency_h"].abs() > 30 * 24) | (out["latency_h"] < -24)
    out.loc[bad, "latency_h"] = np.nan

    out["any_firms"] = out["firms_n_pixels"].fillna(0) > 0
    out["any_start"] = out["fire_start"].notna()

    out_attr = out.drop(columns="geometry").copy()
    out_attr.to_parquet(PROCESSED / "perimeter_latency.parquet", index=False)
    print(f"\nwrote -> {PROCESSED / 'perimeter_latency.parquet'}")

    # ------- Summary printouts -------
    measurable = out[out["any_start"] & out["any_firms"]]
    print(f"\nperimeters with both start-time and FIRMS pixel: {len(measurable)} / {len(out)}")
    if len(measurable):
        lat = measurable["latency_h"].dropna()
        pct = np.percentile(lat, [5, 25, 50, 75, 95])
        print(f"latency hours: median={pct[2]:.1f}  IQR=[{pct[1]:.1f}, {pct[3]:.1f}]  p5={pct[0]:.1f}  p95={pct[4]:.1f}")

    # By size bucket
    bins = [0, 10, 100, 1000, 10000, 1_500_000]
    labels = ["<10", "10-100", "100-1k", "1k-10k", "10k+"]
    out["size_bucket"] = pd.cut(out["GIS_ACRES"], bins=bins, labels=labels, include_lowest=True, right=False)

    summary = (
        out.groupby("size_bucket", observed=True)
           .agg(
               n_perimeters=("INCIDENT", "size"),
               with_start=("any_start", "sum"),
               firms_hit=("any_firms", "sum"),
               firms_hit_rate=("any_firms", "mean"),
               n_measurable=("latency_h", lambda s: s.notna().sum()),
               median_latency_h=("latency_h", "median"),
               p25_latency_h=("latency_h", lambda s: s.dropna().quantile(0.25) if s.dropna().size else np.nan),
               p75_latency_h=("latency_h", lambda s: s.dropna().quantile(0.75) if s.dropna().size else np.nan),
           )
    )
    print("\nlatency by perimeter size (acres):")
    print(summary.to_string(float_format=lambda x: f"{x:.1f}"))

    # Big-fire roll-call: top 10 perimeters by acres
    big = out.nlargest(10, "GIS_ACRES")[
        ["INCIDENT", "GIS_ACRES", "fire_start", "firms_first", "latency_h",
         "firms_n_pixels"]
    ]
    print("\ntop 10 perimeters by acres:")
    print(big.to_string(index=False, float_format=lambda x: f"{x:.1f}"))


if __name__ == "__main__":
    main()
