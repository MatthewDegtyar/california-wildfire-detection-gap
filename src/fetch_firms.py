"""Fetch FIRMS VIIRS VNP14 (Suomi-NPP) active-fire detections for California.

The FIRMS area API returns at most ~10 days per request, so we walk the season
in 10-day windows. CSVs land in data/raw/firms/, concatenated parquet in
data/processed/firms_ca_2020.parquet.

Why VIIRS not MODIS: see start.md — MODIS MOD14 mask is too stochastic for
next-day prediction; VIIRS VNP14 is the preferred product.
"""

from __future__ import annotations

import io
import sys
import time
from datetime import date, timedelta
from pathlib import Path

import pandas as pd
import requests

from src.config import (
    CA_BBOX,
    FIRMS_AREA_URL,
    FIRMS_MAP_KEY,
    FIRMS_RAW,
    FIRMS_SOURCE,
    PROCESSED,
    SEASON_END,
    SEASON_START,
)

WINDOW_DAYS = 5  # FIRMS area-API archive max is 5 days per request


def date_windows(start: str, end: str, step_days: int):
    s = date.fromisoformat(start)
    e = date.fromisoformat(end)
    cur = s
    while cur <= e:
        nxt = min(cur + timedelta(days=step_days - 1), e)
        span = (nxt - cur).days + 1
        yield cur.isoformat(), span
        cur = nxt + timedelta(days=1)


def fetch_window(start_date: str, day_range: int) -> pd.DataFrame:
    w, s, e, n = CA_BBOX
    url = FIRMS_AREA_URL.format(
        key=FIRMS_MAP_KEY,
        source=FIRMS_SOURCE,
        w=w, s=s, e=e, n=n,
        day_range=day_range,
        date=start_date,
    )
    r = requests.get(url, timeout=120)
    r.raise_for_status()
    text = r.text
    # FIRMS returns plain text error messages with HTTP 200 on bad keys etc.
    if not text.lstrip().lower().startswith("latitude"):
        snippet = text[:300].replace("\n", " ")
        raise RuntimeError(f"FIRMS unexpected response for {start_date}+{day_range}: {snippet}")
    if text.count("\n") <= 1:
        return pd.DataFrame()
    return pd.read_csv(io.StringIO(text))


def main():
    if not FIRMS_MAP_KEY:
        sys.exit("FIRMS_MAP_KEY not set (check .env)")

    FIRMS_RAW.mkdir(parents=True, exist_ok=True)
    PROCESSED.mkdir(parents=True, exist_ok=True)

    frames = []
    for start_date, span in date_windows(SEASON_START, SEASON_END, WINDOW_DAYS):
        out_csv = FIRMS_RAW / f"viirs_ca_{start_date}_{span}d.csv"
        if out_csv.exists():
            print(f"  cached {out_csv.name}")
            df = pd.read_csv(out_csv) if out_csv.stat().st_size > 0 else pd.DataFrame()
        else:
            print(f"  fetching {start_date} +{span}d ...", flush=True)
            df = fetch_window(start_date, span)
            df.to_csv(out_csv, index=False)
            time.sleep(0.5)  # be polite
        if not df.empty:
            frames.append(df)

    if not frames:
        sys.exit("No FIRMS rows returned for the window.")

    all_df = pd.concat(frames, ignore_index=True)
    # acq_date is ISO; acq_time is HHMM in UTC. Build a real timestamp.
    all_df["acq_time"] = all_df["acq_time"].astype(str).str.zfill(4)
    all_df["acq_datetime_utc"] = pd.to_datetime(
        all_df["acq_date"] + " " + all_df["acq_time"].str[:2] + ":" + all_df["acq_time"].str[2:],
        utc=True,
        errors="coerce",
    )
    out = PROCESSED / "firms_ca_2020.parquet"
    all_df.to_parquet(out, index=False)
    print(f"\nWrote {len(all_df):,} detections -> {out}")
    print(all_df.head(3).to_string())
    print("\nday/night counts:")
    print(all_df.get("daynight", pd.Series(dtype=object)).value_counts())
    print("\nconfidence distribution:")
    print(all_df.get("confidence", pd.Series(dtype=object)).value_counts())


if __name__ == "__main__":
    main()
