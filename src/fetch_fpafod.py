"""Download FPA-FOD (Fire Program Analysis Fire-Occurrence Database, RDS-2013-0009.6)
and filter to California, 2020.

FPA-FOD covers fires reported by federal, state, and local agencies for 1992-2020.
Unlike CAL FIRE incidents, it includes very small fires — critical for measuring
FIRMS small-fire miss rate (the project's whole point).
"""

from __future__ import annotations

import shutil
import sqlite3
import sys
import zipfile
from pathlib import Path

import pandas as pd
import requests

from src.config import FPAFOD_RAW, PROCESSED

ZIP_URL = (
    "https://www.fs.usda.gov/rds/archive/products/RDS-2013-0009.6/"
    "RDS-2013-0009.6_Data_Format4_SQLITE.zip"
)


def download(url: str, dest: Path) -> None:
    print(f"downloading {url}")
    with requests.get(url, stream=True, timeout=600, headers={"User-Agent": "Mozilla/5.0"}) as r:
        r.raise_for_status()
        total = int(r.headers.get("content-length", 0))
        seen = 0
        last_pct = -1
        with dest.open("wb") as f:
            for chunk in r.iter_content(chunk_size=1024 * 256):
                if chunk:
                    f.write(chunk)
                    seen += len(chunk)
                    if total:
                        pct = int(seen / total * 100)
                        if pct >= last_pct + 10:
                            print(f"  {pct}% ({seen/1e6:.1f} MB)")
                            last_pct = pct
    print(f"  done -> {dest} ({dest.stat().st_size/1e6:.1f} MB)")


def main():
    FPAFOD_RAW.mkdir(parents=True, exist_ok=True)
    PROCESSED.mkdir(parents=True, exist_ok=True)

    zip_path = FPAFOD_RAW / "RDS-2013-0009.6_SQLITE.zip"
    if not zip_path.exists():
        download(ZIP_URL, zip_path)
    else:
        print(f"cached zip ({zip_path.stat().st_size/1e6:.1f} MB)")

    extract_dir = FPAFOD_RAW / "extracted"
    if not extract_dir.exists():
        extract_dir.mkdir()
        with zipfile.ZipFile(zip_path) as z:
            z.extractall(extract_dir)
        print(f"extracted -> {extract_dir}")

    sqlites = list(extract_dir.rglob("*.sqlite"))
    if not sqlites:
        sys.exit(f"no .sqlite in {extract_dir}: {list(extract_dir.rglob('*'))[:10]}")
    db = sqlites[0]
    print(f"sqlite: {db}")

    con = sqlite3.connect(db)
    tables = pd.read_sql("SELECT name FROM sqlite_master WHERE type='table'", con)
    print("tables:")
    print(tables.to_string(index=False))

    # The main table is 'Fires' in recent FPA-FOD releases.
    table = "Fires" if "Fires" in tables["name"].values else tables["name"].iloc[0]
    cols = pd.read_sql(f"PRAGMA table_info({table})", con)
    print(f"\n{table} columns ({len(cols)}):", list(cols["name"]))

    q = f"""
        SELECT *
        FROM {table}
        WHERE STATE = 'CA' AND FIRE_YEAR = 2020
    """
    df = pd.read_sql(q, con)
    con.close()
    print(f"\nCA 2020 rows: {len(df):,}")

    # Build a real discovery datetime (date + optional time)
    df["DISCOVERY_DATE"] = pd.to_datetime(df["DISCOVERY_DATE"], errors="coerce")
    if "DISCOVERY_TIME" in df.columns:
        t = df["DISCOVERY_TIME"].astype(str).str.zfill(4)
        df["DISCOVERY_DT"] = pd.to_datetime(
            df["DISCOVERY_DATE"].dt.strftime("%Y-%m-%d") + " " + t.str[:2] + ":" + t.str[2:],
            errors="coerce",
        )
    season = df[
        (df["DISCOVERY_DATE"] >= "2020-06-01") & (df["DISCOVERY_DATE"] < "2020-12-01")
    ].copy()

    print(f"\nfire-season subset (Jun-Nov 2020): {len(season):,}")
    if "FIRE_SIZE_CLASS" in season.columns:
        print("\nsize-class distribution:")
        print(season["FIRE_SIZE_CLASS"].value_counts().sort_index())
    if "FIRE_SIZE" in season.columns:
        print(f"\nFIRE_SIZE acres: median={season['FIRE_SIZE'].median():.2f}  "
              f"mean={season['FIRE_SIZE'].mean():.1f}  max={season['FIRE_SIZE'].max():,.0f}")

    out = PROCESSED / "fpafod_ca_2020.parquet"
    season.to_parquet(out, index=False)
    print(f"\nwrote -> {out}")


if __name__ == "__main__":
    main()
