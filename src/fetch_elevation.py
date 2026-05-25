"""Sample elevation at (a) every FPA-FOD CA-2020 fire and (b) every cell of the
0.1-deg CA grid used by gap_surface.py. Source: Open-Elevation API
(free, no key, SRTM-based; ~200 points/request).

Cached to data/processed/elevation_cache.parquet keyed by (lat_r, lon_r) at
0.001-deg precision so re-runs are free. The cache is written incrementally
every CHECKPOINT_BATCHES batches so a network failure doesn't lose progress.
"""

from __future__ import annotations

import time

import numpy as np
import pandas as pd
import requests

from src.config import CA_BBOX, PROCESSED

OPEN_ELEVATION = "https://api.open-elevation.com/api/v1/lookup"
BATCH = 200
SLEEP = 0.3
CHECKPOINT_BATCHES = 5


def _fetch_batch(lats, lons):
    payload = {"locations": [{"latitude": float(la), "longitude": float(lo)} for la, lo in zip(lats, lons)]}
    last_err = None
    for attempt in range(6):
        try:
            r = requests.post(OPEN_ELEVATION, json=payload, timeout=120,
                              headers={"Content-Type": "application/json"})
            if r.status_code == 200:
                results = r.json()["results"]
                # Open-Elevation does NOT preserve input order — match by lat/lon
                want = list(zip(lats, lons))
                got = {(round(d["latitude"], 6), round(d["longitude"], 6)): d["elevation"] for d in results}
                return [got[(round(la, 6), round(lo, 6))] for la, lo in want]
            last_err = f"http {r.status_code}"
        except requests.RequestException as e:
            last_err = repr(e)
        time.sleep(2 ** attempt)
    raise RuntimeError(f"Open-Elevation failed after retries: {last_err}")


def fetch_elevations(points: pd.DataFrame, cache_path) -> pd.Series:
    """`points` has columns lat, lon; returns Series aligned to its index."""
    if cache_path.exists():
        cache = pd.read_parquet(cache_path)
        cache.set_index(["lat_r", "lon_r"], inplace=True)
    else:
        cache = pd.DataFrame(columns=["elevation_m"]).set_index(pd.MultiIndex.from_tuples([], names=["lat_r", "lon_r"]))

    pts = points.copy()
    pts["lat_r"] = pts["lat"].round(3)
    pts["lon_r"] = pts["lon"].round(3)

    # Identify which rounded points need fetching
    keys = pts[["lat_r", "lon_r"]].drop_duplicates()
    have = keys.merge(cache.reset_index(), on=["lat_r", "lon_r"], how="left")
    missing = have[have["elevation_m"].isna()][["lat_r", "lon_r"]].reset_index(drop=True)
    print(f"need {len(missing):,} fresh elevation lookups (cached: {len(cache):,})")

    # Parallelize across 4 workers — Open-Elevation tolerates concurrent posts.
    from concurrent.futures import ThreadPoolExecutor, as_completed
    new_rows = []
    blocks = [missing.iloc[i:i + BATCH] for i in range(0, len(missing), BATCH)]

    def _run(idx_block):
        idx, block = idx_block
        return idx, list(zip(
            block["lat_r"].values, block["lon_r"].values,
            _fetch_batch(block["lat_r"].values, block["lon_r"].values),
        ))

    completed = 0
    with ThreadPoolExecutor(max_workers=4) as ex:
        futures = {ex.submit(_run, (i, b)): i for i, b in enumerate(blocks)}
        for fut in as_completed(futures):
            i, rows = fut.result()
            new_rows.extend(rows)
            completed += 1
            if completed % 5 == 0:
                pts_done = len(new_rows)
                print(f"  fetched {pts_done:,} / {len(missing):,}  ({completed}/{len(blocks)} batches)", flush=True)
                fresh = pd.DataFrame(new_rows, columns=["lat_r", "lon_r", "elevation_m"]).set_index(["lat_r", "lon_r"])
                cache_snapshot = pd.concat([cache, fresh])
                cache_snapshot.reset_index().drop_duplicates(["lat_r", "lon_r"]).to_parquet(cache_path, index=False)

    if new_rows:
        fresh = pd.DataFrame(new_rows, columns=["lat_r", "lon_r", "elevation_m"]).set_index(["lat_r", "lon_r"])
        cache = pd.concat([cache, fresh])
        cache.reset_index().drop_duplicates(["lat_r", "lon_r"]).to_parquet(cache_path, index=False)

    elev = pts[["lat_r", "lon_r"]].merge(cache.reset_index(), on=["lat_r", "lon_r"], how="left")
    return elev["elevation_m"].values


def main():
    cache_path = PROCESSED / "elevation_cache.parquet"

    # FPA-FOD points
    fpa = pd.read_parquet(PROCESSED / "fpafod_ca_2020.parquet")
    fpa_pts = pd.DataFrame({"lat": fpa["LATITUDE"], "lon": fpa["LONGITUDE"]})
    print(f"FPA-FOD points to enrich: {len(fpa_pts):,}")

    # 0.1-deg CA grid
    w, s, e, n = CA_BBOX
    GRID = 0.1
    lons = np.arange(w, e + 1e-9, GRID)
    lats = np.arange(s, n + 1e-9, GRID)
    lon_g, lat_g = np.meshgrid(lons, lats)
    grid_pts = pd.DataFrame({"lat": lat_g.ravel(), "lon": lon_g.ravel()})
    print(f"grid points: {len(grid_pts):,}")

    all_pts = pd.concat([fpa_pts, grid_pts], ignore_index=True)
    elev = fetch_elevations(all_pts, cache_path)
    print(f"\nfetched {len(elev):,} elevations. cache size now: "
          f"{pd.read_parquet(cache_path).shape[0]:,}")

    fpa_elev = elev[: len(fpa_pts)]
    grid_elev = elev[len(fpa_pts):]

    fpa["elevation_m"] = fpa_elev
    out_fpa = PROCESSED / "fpafod_ca_2020_with_elev.parquet"
    fpa.to_parquet(out_fpa, index=False)
    print(f"wrote -> {out_fpa}")
    print(f"FPA-FOD elevation stats: min={np.nanmin(fpa_elev):.0f}m  median={np.nanmedian(fpa_elev):.0f}m  max={np.nanmax(fpa_elev):.0f}m")

    grid_df = grid_pts.copy()
    grid_df["elevation_m"] = grid_elev
    out_grid = PROCESSED / "grid_elev.parquet"
    grid_df.to_parquet(out_grid, index=False)
    print(f"wrote -> {out_grid}")


if __name__ == "__main__":
    main()
