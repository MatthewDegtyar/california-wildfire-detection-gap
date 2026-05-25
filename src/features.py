"""Build the feature matrix used by baselines, the detection-gap model,
and the spatial gap-surface prediction.

Inputs: data/processed/fpafod_with_firms_match_v1.parquet
Outputs: pandas DataFrame with target `firms_hit` and a tidy feature set.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from src.config import PROCESSED


# VIIRS Suomi-NPP local equator crossing ~01:30 / 13:30. CA latitudes shift a few
# minutes later. Use simple anchors at 02:00 and 14:00 local; that's the resolution
# we need for an interpretable "hours_since_last_overpass" feature.
OVERPASS_LOCAL_HOURS = (2.0, 14.0)


def _hours_since_last_overpass(hour: float) -> float:
    """Given a local hour-of-day, hours since the most-recent VIIRS overpass."""
    if pd.isna(hour):
        return np.nan
    candidates = []
    for h in OVERPASS_LOCAL_HOURS:
        diff = (hour - h) % 24
        candidates.append(diff)
    return min(candidates)


def build(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()

    df["log_size"] = np.log10(df["FIRE_SIZE"].clip(lower=1e-3))
    df["discovery_doy"] = pd.to_datetime(df["DISCOVERY_DATE"]).dt.dayofyear
    df["sin_doy"] = np.sin(2 * np.pi * df["discovery_doy"] / 366)
    df["cos_doy"] = np.cos(2 * np.pi * df["discovery_doy"] / 366)

    # DISCOVERY_TIME is HHMM local (where present). Convert to fractional hour.
    if "DISCOVERY_TIME" in df.columns:
        t = pd.to_numeric(df["DISCOVERY_TIME"], errors="coerce")
        hh = (t // 100).clip(upper=23)
        mm = (t % 100).clip(upper=59)
        df["disc_hour"] = hh + mm / 60.0
    else:
        df["disc_hour"] = np.nan
    df["hours_since_overpass"] = df["disc_hour"].apply(_hours_since_last_overpass)

    # Cause grouping — collapse to a coarse set so cardinality stays low
    if "NWCG_GENERAL_CAUSE" in df.columns:
        df["cause"] = df["NWCG_GENERAL_CAUSE"].fillna("Unknown")
    else:
        df["cause"] = "Unknown"

    # Drop rows with no usable target / coords (a handful)
    df = df.dropna(subset=["LATITUDE", "LONGITUDE", "FIRE_SIZE"])

    return df


def load_modeling_frame() -> pd.DataFrame:
    return build(pd.read_parquet(PROCESSED / "fpafod_with_firms_match_v1.parquet"))


if __name__ == "__main__":
    df = load_modeling_frame()
    print(df[["firms_hit", "FIRE_SIZE", "log_size", "discovery_doy", "disc_hour",
              "hours_since_overpass", "LATITUDE", "LONGITUDE", "cause"]].head().to_string())
    print(f"\nrows: {len(df)}  hit rate: {df['firms_hit'].mean():.3f}")
    print(f"disc_hour missing: {df['disc_hour'].isna().mean():.1%}")
    print(f"\ncauses:")
    print(df["cause"].value_counts())
