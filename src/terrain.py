"""Compute slope, aspect, and TPI (Topographic Position Index) at every FPA-FOD
point and every CA grid cell.

For each location we need elevation at 4 neighbors (N/S/E/W) at a small offset.
For FPA points we fetch neighbors from Open-Elevation (via fetch_elevation's
parallel cache); for grid cells we just use the adjacent cells from the existing
0.1-deg elevation grid.

  slope_deg   = arctan( sqrt((dz/dx)^2 + (dz/dy)^2) )       in degrees
  aspect      = atan2(dz/dx, -dz/dy)                         radians, then sin/cos
  TPI         = elev_center - mean(elev_neighbors)
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from src.config import CA_BBOX, PROCESSED
from src.fetch_elevation import fetch_elevations

OFFSET_DEG = 0.005   # ~555 m at CA latitudes — fine enough to see local slope
GRID_DEG = 0.1


def _ns_ew(lat: float, lon: float) -> dict:
    return {
        "N": (lat + OFFSET_DEG, lon),
        "S": (lat - OFFSET_DEG, lon),
        "E": (lat, lon + OFFSET_DEG),
        "W": (lat, lon - OFFSET_DEG),
    }


def derive(elev_c, elev_n, elev_s, elev_e, elev_w, dy_m, dx_m):
    dz_dy = (elev_n - elev_s) / (2 * dy_m)
    dz_dx = (elev_e - elev_w) / (2 * dx_m)
    slope = np.degrees(np.arctan(np.sqrt(dz_dx ** 2 + dz_dy ** 2)))
    aspect = np.arctan2(dz_dx, -dz_dy)  # radians
    tpi = elev_c - 0.25 * (elev_n + elev_s + elev_e + elev_w)
    return slope, np.sin(aspect), np.cos(aspect), tpi


def main():
    cache_path = PROCESSED / "elevation_cache.parquet"
    fpa = pd.read_parquet(PROCESSED / "fpafod_ca_2020_with_elev.parquet")

    # Build neighbor lookups for FPA points
    needed = []
    for _, r in fpa.iterrows():
        for d, (la, lo) in _ns_ew(r["LATITUDE"], r["LONGITUDE"]).items():
            needed.append({"lat": la, "lon": lo})
    neigh_df = pd.DataFrame(needed)
    print(f"need {len(neigh_df):,} neighbor elevations for FPA")
    neigh_elev = fetch_elevations(neigh_df, cache_path)

    # back into N/S/E/W per row
    e_n = neigh_elev[0::4]
    e_s = neigh_elev[1::4]
    e_e = neigh_elev[2::4]
    e_w = neigh_elev[3::4]
    e_c = fpa["elevation_m"].values

    # Distance in meters for 0.005 deg
    # 1 deg lat ~ 111,320 m; 1 deg lon ~ 111,320 * cos(lat)
    lat = fpa["LATITUDE"].values
    dy_m = OFFSET_DEG * 111_320.0
    dx_m = OFFSET_DEG * 111_320.0 * np.cos(np.radians(lat))

    slope, sin_a, cos_a, tpi = derive(e_c, e_n, e_s, e_e, e_w, dy_m, dx_m)
    fpa["slope_deg"] = slope
    fpa["aspect_sin"] = sin_a
    fpa["aspect_cos"] = cos_a
    fpa["tpi_m"] = tpi

    print(f"slope_deg: median={np.nanmedian(slope):.1f}  max={np.nanmax(slope):.1f}")
    print(f"tpi_m: median={np.nanmedian(tpi):.1f}  IQR=[{np.nanquantile(tpi,0.25):.1f}, {np.nanquantile(tpi,0.75):.1f}]")
    out = PROCESSED / "fpafod_ca_2020_with_terrain.parquet"
    fpa.to_parquet(out, index=False)
    print(f"wrote -> {out}")

    # Now do it for the gap-surface grid using existing 0.1-deg neighbors
    grid = pd.read_parquet(PROCESSED / "grid_elev.parquet")
    w, s, e, n = CA_BBOX
    lons = np.arange(w, e + 1e-9, GRID_DEG)
    lats = np.arange(s, n + 1e-9, GRID_DEG)
    nx, ny = len(lons), len(lats)
    elev_grid = grid["elevation_m"].values.reshape(ny, nx)

    # Roll-shift to get neighbors. Edges fall back to center (slope ~ 0 at boundary).
    e_c2 = elev_grid
    e_n2 = np.roll(elev_grid, -1, axis=0); e_n2[-1, :] = elev_grid[-1, :]
    e_s2 = np.roll(elev_grid,  1, axis=0); e_s2[0, :]  = elev_grid[0, :]
    e_e2 = np.roll(elev_grid, -1, axis=1); e_e2[:, -1] = elev_grid[:, -1]
    e_w2 = np.roll(elev_grid,  1, axis=1); e_w2[:, 0]  = elev_grid[:, 0]

    lat_g, lon_g = np.meshgrid(lats, lons, indexing="ij")
    dy = GRID_DEG * 111_320.0
    dx = GRID_DEG * 111_320.0 * np.cos(np.radians(lat_g))
    slope_g, sin_g, cos_g, tpi_g = derive(e_c2, e_n2, e_s2, e_e2, e_w2, dy, dx)

    grid["slope_deg"] = slope_g.ravel()
    grid["aspect_sin"] = sin_g.ravel()
    grid["aspect_cos"] = cos_g.ravel()
    grid["tpi_m"] = tpi_g.ravel()
    print(f"\ngrid slope_deg: median={np.nanmedian(grid['slope_deg']):.1f}  max={np.nanmax(grid['slope_deg']):.1f}")
    grid_out = PROCESSED / "grid_terrain.parquet"
    grid.to_parquet(grid_out, index=False)
    print(f"wrote -> {grid_out}")


if __name__ == "__main__":
    main()
