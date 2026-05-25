"""Sample LANDFIRE FBFM40 (Fire Behavior Fuel Model, 40-class Scott & Burgan)
at every FPA-FOD point and every CA grid cell.

Source: USGS LANDFIRE LF2016 ImageServer, /getSamples endpoint with multipoint
geometry. ~1000 points per call, 4 concurrent calls.

FBFM40 raw codes (selected — for full list see Scott & Burgan 2005):
   91-99   non-burnable (urban, ag, water, snow, barren, dev)
  101-109  GR Grass
  121-124  GS Grass-Shrub
  141-149  SH Shrub
  161-165  TU Timber-Understory
  181-189  TL Timber Litter
  201-204  SB Slash-Blowdown

Coarse grouping into 6 buckets is recorded in `fuel_group` to keep the
modeling-side cardinality low.
"""

from __future__ import annotations

import json
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

import numpy as np
import pandas as pd
import requests

from src.config import CA_BBOX, PROCESSED

URL = ("https://lfps.usgs.gov/arcgis/rest/services/Landfire_LF2016/"
       "LF2016_FBFM40_CONUS/ImageServer/getSamples")
BATCH = 800
WORKERS = 4


def fuel_group(code):
    try:
        c = int(code)
    except (ValueError, TypeError):
        return "Unknown"
    if 91 <= c <= 99:
        return "Non-burnable"
    if 101 <= c <= 109:
        return "Grass"
    if 121 <= c <= 124:
        return "Grass-Shrub"
    if 141 <= c <= 149:
        return "Shrub"
    if 161 <= c <= 165:
        return "Timber-Understory"
    if 181 <= c <= 189:
        return "Timber-Litter"
    if 201 <= c <= 204:
        return "Slash-Blowdown"
    return "Other"


def _post_batch(pts):
    geometry = json.dumps({"points": pts, "spatialReference": {"wkid": 4326}})
    last_err = None
    for attempt in range(5):
        try:
            r = requests.post(
                URL,
                data={
                    "geometry": geometry,
                    "geometryType": "esriGeometryMultipoint",
                    "returnFirstValueOnly": "true",
                    "f": "json",
                },
                timeout=120,
                headers={"User-Agent": "Mozilla/5.0"},
            )
            if r.status_code == 200:
                samples = r.json().get("samples", [])
                # samples include `locationId` corresponding to input order
                out = ["NoData"] * len(pts)
                for s in samples:
                    out[int(s["locationId"])] = s["value"]
                return out
            last_err = f"http {r.status_code}: {r.text[:80]}"
        except requests.RequestException as e:
            last_err = repr(e)
        time.sleep(2 ** attempt)
    raise RuntimeError(f"LANDFIRE batch failed: {last_err}")


def fetch_fuel(lat_lon: pd.DataFrame, cache_path) -> list:
    """`lat_lon` columns lat, lon. Returns list aligned to its rows."""
    if cache_path.exists():
        cache = pd.read_parquet(cache_path)
    else:
        cache = pd.DataFrame(columns=["lat_r", "lon_r", "fbfm40"])
    cache_idx = cache.set_index(["lat_r", "lon_r"])["fbfm40"].to_dict()

    pts = lat_lon.copy()
    pts["lat_r"] = pts["lat"].round(3)
    pts["lon_r"] = pts["lon"].round(3)
    pts["fbfm40"] = [cache_idx.get((la, lo)) for la, lo in zip(pts["lat_r"], pts["lon_r"])]

    missing = pts[pts["fbfm40"].isna()][["lat_r", "lon_r"]].drop_duplicates().reset_index(drop=True)
    print(f"need {len(missing):,} LANDFIRE lookups (cached {len(cache):,})")

    blocks = []
    for i in range(0, len(missing), BATCH):
        chunk = missing.iloc[i:i + BATCH]
        blocks.append((i, chunk))

    new_rows = []
    done = 0
    with ThreadPoolExecutor(max_workers=WORKERS) as ex:
        futures = {
            ex.submit(_post_batch, [[float(lo), float(la)] for la, lo in zip(c["lat_r"], c["lon_r"])]): (i, c)
            for i, c in blocks
        }
        for fut in as_completed(futures):
            i, c = futures[fut]
            vals = fut.result()
            new_rows.extend(zip(c["lat_r"], c["lon_r"], vals))
            done += 1
            if done % 5 == 0:
                pts_done = len(new_rows)
                print(f"  fetched {pts_done:,} / {len(missing):,}  ({done}/{len(blocks)} batches)", flush=True)
                fresh = pd.DataFrame(new_rows, columns=["lat_r", "lon_r", "fbfm40"])
                pd.concat([cache, fresh], ignore_index=True).drop_duplicates(["lat_r", "lon_r"]).to_parquet(cache_path, index=False)

    if new_rows:
        fresh = pd.DataFrame(new_rows, columns=["lat_r", "lon_r", "fbfm40"])
        cache = pd.concat([cache, fresh], ignore_index=True).drop_duplicates(["lat_r", "lon_r"])
        cache.to_parquet(cache_path, index=False)

    cache_idx = cache.set_index(["lat_r", "lon_r"])["fbfm40"].to_dict()
    return [cache_idx.get((la, lo), "NoData") for la, lo in zip(pts["lat_r"], pts["lon_r"])]


def main():
    cache_path = PROCESSED / "fuel_cache.parquet"

    fpa = pd.read_parquet(PROCESSED / "fpafod_ca_2020_with_terrain.parquet")
    fpa_pts = pd.DataFrame({"lat": fpa["LATITUDE"], "lon": fpa["LONGITUDE"]})

    w, s, e, n = CA_BBOX
    lons = np.arange(w, e + 1e-9, 0.1)
    lats = np.arange(s, n + 1e-9, 0.1)
    lon_g, lat_g = np.meshgrid(lons, lats)
    grid_pts = pd.DataFrame({"lat": lat_g.ravel(), "lon": lon_g.ravel()})

    all_pts = pd.concat([fpa_pts, grid_pts], ignore_index=True)
    vals = fetch_fuel(all_pts, cache_path)
    fpa_vals = vals[: len(fpa_pts)]
    grid_vals = vals[len(fpa_pts):]

    fpa["fbfm40"] = fpa_vals
    fpa["fuel_group"] = [fuel_group(v) for v in fpa_vals]
    fpa.to_parquet(PROCESSED / "fpafod_ca_2020_with_fuel.parquet", index=False)
    print(f"FPA fuel groups:")
    print(fpa["fuel_group"].value_counts())

    grid_terrain = pd.read_parquet(PROCESSED / "grid_terrain.parquet")
    grid_terrain["fbfm40"] = grid_vals
    grid_terrain["fuel_group"] = [fuel_group(v) for v in grid_vals]
    grid_terrain.to_parquet(PROCESSED / "grid_terrain_fuel.parquet", index=False)
    print(f"\nGrid fuel groups:")
    print(grid_terrain["fuel_group"].value_counts())


if __name__ == "__main__":
    main()
