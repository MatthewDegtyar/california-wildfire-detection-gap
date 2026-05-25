"""Fetch CAL FIRE public incident records for the 2020 fire season."""

from __future__ import annotations

import json
import sys

import pandas as pd
import requests

from src.config import CALFIRE_RAW, PROCESSED

URL = "https://incidents.fire.ca.gov/umbraco/api/IncidentApi/List?year=2020&inactive=true"


def main():
    CALFIRE_RAW.mkdir(parents=True, exist_ok=True)
    PROCESSED.mkdir(parents=True, exist_ok=True)

    raw_path = CALFIRE_RAW / "calfire_incidents_2020.json"
    if raw_path.exists():
        print(f"cached {raw_path}")
        rows = json.loads(raw_path.read_text())
    else:
        r = requests.get(URL, timeout=120, headers={"User-Agent": "Mozilla/5.0"})
        r.raise_for_status()
        rows = r.json()
        raw_path.write_text(json.dumps(rows))
        print(f"saved {len(rows)} incidents -> {raw_path}")

    df = pd.DataFrame(rows)
    df["Started"] = pd.to_datetime(df["Started"], utc=True, errors="coerce")
    df["Updated"] = pd.to_datetime(df["Updated"], utc=True, errors="coerce")
    df["AcresBurned"] = pd.to_numeric(df["AcresBurned"], errors="coerce")
    df["Latitude"] = pd.to_numeric(df["Latitude"], errors="coerce")
    df["Longitude"] = pd.to_numeric(df["Longitude"], errors="coerce")

    # Keep wildfires that actually started in the fire-season window
    season = df[
        (df["Type"].str.lower() == "wildfire")
        & (df["Started"] >= "2020-06-01")
        & (df["Started"] < "2020-12-01")
    ].copy()

    out = PROCESSED / "calfire_incidents_2020.parquet"
    season.to_parquet(out, index=False)
    print(f"\n{len(season)} wildfire incidents Jun-Nov 2020 (from {len(df)} total)")
    print(f"acres: mean={season['AcresBurned'].mean():.0f}  median={season['AcresBurned'].median():.0f}  max={season['AcresBurned'].max():,.0f}")
    print("\nsize distribution:")
    bins = [0, 10, 100, 300, 1000, 10_000, 100_000, 1_500_000]
    labels = ["0-10", "10-100", "100-300", "300-1k", "1k-10k", "10k-100k", "100k+"]
    print(pd.cut(season["AcresBurned"], bins=bins, labels=labels, include_lowest=True, right=False).value_counts().sort_index())
    print(f"\nwrote -> {out}")


if __name__ == "__main__":
    main()
