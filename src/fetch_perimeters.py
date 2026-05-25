"""Download CA 2020 fire perimeters from the NIFC InterAgency Fire Perimeter History.

The ArcGIS REST endpoint pages results, so we walk with resultOffset until the
exceededTransferLimit flag clears. Output: a single GeoPackage with one feature
per perimeter, plus a parquet sidecar of the attribute table.
"""

from __future__ import annotations

import json

import geopandas as gpd
import pandas as pd
import requests
from shapely.geometry import shape

from src.config import CALFIRE_RAW, PROCESSED

SERVICE = (
    "https://services3.arcgis.com/T4QMspbfLg3qTGWY/ArcGIS/rest/services/"
    "InterAgencyFirePerimeterHistory_All_Years_View/FeatureServer/0/query"
)


def fetch_all(where: str, out_fields: str) -> list[dict]:
    page = 0
    offset = 0
    rows = []
    while True:
        params = {
            "where": where,
            "outFields": out_fields,
            "outSR": "4326",
            "f": "geojson",
            "resultOffset": offset,
            "resultRecordCount": 200,
            "orderByFields": "OBJECTID",
        }
        r = requests.get(SERVICE, params=params, timeout=120,
                         headers={"User-Agent": "Mozilla/5.0"})
        r.raise_for_status()
        j = r.json()
        feats = j.get("features", [])
        if not feats:
            break
        rows.extend(feats)
        print(f"  page {page}: +{len(feats)}  (total {len(rows)})")
        if not j.get("properties", {}).get("exceededTransferLimit"):
            break
        offset += len(feats)
        page += 1
    return rows


def main():
    CALFIRE_RAW.mkdir(parents=True, exist_ok=True)
    PROCESSED.mkdir(parents=True, exist_ok=True)

    raw_path = CALFIRE_RAW / "perimeters_ca_2020.geojson"
    if raw_path.exists():
        print(f"cached {raw_path}")
        feats = json.loads(raw_path.read_text())["features"]
    else:
        feats = fetch_all(
            where="FIRE_YEAR='2020' AND UNIT_ID LIKE 'CA%'",
            out_fields="OBJECTID,IRWINID,INCIDENT,FIRE_YEAR,GIS_ACRES,DATE_CUR,UNIT_ID,AGENCY,SOURCE,COMMENTS",
        )
        raw_path.write_text(json.dumps({"type": "FeatureCollection", "features": feats}))
        print(f"saved {len(feats)} perimeters -> {raw_path}")

    geoms = [shape(f["geometry"]) for f in feats]
    props = [f["properties"] for f in feats]
    gdf = gpd.GeoDataFrame(props, geometry=geoms, crs="EPSG:4326")
    gdf["DATE_CUR"] = pd.to_datetime(gdf["DATE_CUR"], unit="ms", errors="coerce", utc=True)
    gdf["GIS_ACRES"] = pd.to_numeric(gdf["GIS_ACRES"], errors="coerce")

    print(f"\n{len(gdf)} perimeters; geom types: {gdf.geometry.geom_type.value_counts().to_dict()}")
    print(f"acres: median={gdf['GIS_ACRES'].median():.0f}  mean={gdf['GIS_ACRES'].mean():.0f}  max={gdf['GIS_ACRES'].max():,.0f}")
    print("\ntop 10 by acres:")
    print(gdf.nlargest(10, "GIS_ACRES")[["INCIDENT", "GIS_ACRES", "DATE_CUR", "AGENCY"]].to_string(index=False))

    out_gpkg = PROCESSED / "perimeters_ca_2020.gpkg"
    gdf.to_file(out_gpkg, driver="GPKG")
    print(f"\nwrote -> {out_gpkg}")

    # Parquet sidecar (attributes only) for quick reads
    pd.DataFrame(gdf.drop(columns="geometry")).to_parquet(
        PROCESSED / "perimeters_ca_2020_attrs.parquet", index=False
    )


if __name__ == "__main__":
    main()
