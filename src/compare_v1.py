"""Refined FIRMS-vs-FPA-FOD comparison.

Improvements over v0:
- Temporal window scales with the fire: from `pre_days` before DISCOVERY_DATE
  through `post_days` after `min(CONT_DATE, DISCOVERY_DATE + max_window_days)`.
  (CAL FIRE / FPA-FOD often record long containment lags; cap so that a multi-month
  containment doesn't sweep up unrelated nearby ignitions.)
- Records `n_pixels` (count of matching detections), not just hit/miss, so we can
  reason about persistence — a single pixel could be noise, hundreds is the fire.
- Records `time_to_first_detection_h` from DISCOVERY → earliest matching pixel.
- Sensitivity sweep over (radius_km, window_days) so the headline isn't fragile.

Writes the v1 match table to data/processed/fpafod_with_firms_match_v1.parquet
and the sensitivity table to data/processed/sensitivity_v1.parquet.
"""

from __future__ import annotations

from datetime import timedelta

import numpy as np
import pandas as pd

from src.config import PROCESSED

EARTH_R_KM = 6371.0088
DEFAULT_RADIUS_KM = 3.0          # closer than v0; one VIIRS pixel is ~375 m
DEFAULT_PRE_DAYS = 1
DEFAULT_MAX_WINDOW_DAYS = 14     # cap on duration tracked
DEFAULT_POST_DAYS_NO_CONT = 3    # used when CONT_DATE missing


def haversine_km(lat1, lon1, lat2, lon2):
    lat1 = np.radians(lat1); lon1 = np.radians(lon1)
    lat2 = np.radians(lat2); lon2 = np.radians(lon2)
    dlat = lat2 - lat1; dlon = lon2 - lon1
    a = np.sin(dlat / 2)**2 + np.cos(lat1) * np.cos(lat2) * np.sin(dlon / 2)**2
    return 2 * EARTH_R_KM * np.arcsin(np.sqrt(a))


def _parse_cont(s):
    """FPA-FOD CONT_DATE is sometimes 'M/D/YYYY' string, sometimes already datetime."""
    if pd.isna(s) or s == "" or s is None:
        return pd.NaT
    return pd.to_datetime(s, errors="coerce")


def compute_matches(
    firms: pd.DataFrame,
    fpa: pd.DataFrame,
    radius_km: float = DEFAULT_RADIUS_KM,
    pre_days: int = DEFAULT_PRE_DAYS,
    post_days_no_cont: int = DEFAULT_POST_DAYS_NO_CONT,
    max_window_days: int = DEFAULT_MAX_WINDOW_DAYS,
) -> pd.DataFrame:
    """Return a copy of `fpa` with FIRMS-match columns added."""
    firms_by_date = {d: g for d, g in firms.groupby("acq_date_dt")}

    out_hit = np.zeros(len(fpa), dtype=bool)
    out_npix = np.zeros(len(fpa), dtype=np.int32)
    out_first_lag_h = np.full(len(fpa), np.nan)
    out_min_dist = np.full(len(fpa), np.nan)

    for i, row in enumerate(fpa.itertuples(index=False)):
        lat = row.LATITUDE; lon = row.LONGITUDE
        disc = row.DISCOVERY_DATE
        if pd.isna(lat) or pd.isna(lon) or pd.isna(disc):
            continue
        cont = _parse_cont(getattr(row, "CONT_DATE", pd.NaT))
        if pd.isna(cont):
            end_day = disc + timedelta(days=post_days_no_cont)
        else:
            end_day = min(cont, disc + timedelta(days=max_window_days))

        start_day = disc - timedelta(days=pre_days)

        lat_pad = radius_km / 111.0
        lon_pad = radius_km / (111.0 * max(np.cos(np.radians(lat)), 0.1))

        npix = 0
        min_dist = np.inf
        first_dt = None

        day = start_day
        while day <= end_day:
            g = firms_by_date.get(day)
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
            d_km = haversine_km(lat, lon, cand["latitude"].values, cand["longitude"].values)
            in_radius = d_km <= radius_km
            if not in_radius.any():
                continue
            hits = cand.loc[in_radius]
            npix += int(in_radius.sum())
            cur_min = float(d_km[in_radius].min())
            if cur_min < min_dist:
                min_dist = cur_min
            cur_first = hits["acq_datetime_utc"].min()
            if first_dt is None or cur_first < first_dt:
                first_dt = cur_first

        if npix > 0:
            out_hit[i] = True
            out_npix[i] = npix
            out_min_dist[i] = min_dist
            if first_dt is not None and pd.notna(disc):
                lag_h = (first_dt - pd.Timestamp(disc).tz_localize("UTC")).total_seconds() / 3600.0
                out_first_lag_h[i] = lag_h

    fpa = fpa.copy()
    fpa["firms_hit"] = out_hit
    fpa["firms_n_pixels"] = out_npix
    fpa["firms_min_dist_km"] = out_min_dist
    fpa["firms_first_lag_h"] = out_first_lag_h
    return fpa


def _summary(fpa: pd.DataFrame) -> pd.DataFrame:
    bins = [0, 0.25, 1, 10, 100, 300, 1000, 10_000, 100_000, 1_500_000]
    labels = ["<0.25", "0.25-1", "1-10", "10-100", "100-300", "300-1k", "1k-10k", "10k-100k", "100k+"]
    fpa = fpa.assign(size_bucket=pd.cut(fpa["FIRE_SIZE"], bins=bins, labels=labels, include_lowest=True, right=False))
    return (
        fpa.groupby("size_bucket", observed=True)
           .agg(n=("FOD_ID", "size"),
                hit=("firms_hit", "sum"),
                hit_rate=("firms_hit", "mean"))
    )


def main():
    firms = pd.read_parquet(PROCESSED / "firms_ca_2020.parquet")
    fpa = pd.read_parquet(PROCESSED / "fpafod_ca_2020.parquet")

    firms["acq_date_dt"] = pd.to_datetime(firms["acq_date"], errors="coerce")
    fpa["DISCOVERY_DATE"] = pd.to_datetime(fpa["DISCOVERY_DATE"], errors="coerce")

    # 1) Headline run at sensible defaults.
    print(f"v1 defaults: radius={DEFAULT_RADIUS_KM}km, pre={DEFAULT_PRE_DAYS}d, "
          f"post={DEFAULT_POST_DAYS_NO_CONT}d (no CONT), max_window={DEFAULT_MAX_WINDOW_DAYS}d")
    fpa_match = compute_matches(firms, fpa)
    print(f"overall hit rate: {fpa_match['firms_hit'].mean():.1%}")
    print("\nhit rate by acres bucket:")
    print(_summary(fpa_match).to_string(float_format=lambda x: f"{x:.3f}"))

    out = PROCESSED / "fpafod_with_firms_match_v1.parquet"
    fpa_match.to_parquet(out, index=False)
    print(f"\nwrote -> {out}")

    # 2) Sensitivity sweep — does the picture change with looser/tighter envelopes?
    sweeps = []
    print("\nsensitivity sweep:")
    for r in (1.5, 3.0, 5.0):
        for pre in (0, 1):
            for post in (1, 3, 5):
                m = compute_matches(firms, fpa, radius_km=r, pre_days=pre, post_days_no_cont=post)
                rate = m["firms_hit"].mean()
                small = m.loc[m["FIRE_SIZE"] < 10, "firms_hit"].mean()
                big = m.loc[m["FIRE_SIZE"] >= 1000, "firms_hit"].mean()
                row = {"radius_km": r, "pre_days": pre, "post_days_no_cont": post,
                       "overall": rate, "small_lt10": small, "big_ge1k": big}
                sweeps.append(row)
                print(f"  r={r:.1f} pre={pre} post={post}: overall={rate:.3f}  <10ac={small:.3f}  ≥1k ac={big:.3f}")
    sens = pd.DataFrame(sweeps)
    sens.to_parquet(PROCESSED / "sensitivity_v1.parquet", index=False)
    print(f"wrote sweep -> {PROCESSED / 'sensitivity_v1.parquet'}")


if __name__ == "__main__":
    main()
