"""Shared paths and constants for the FIRMS-vs-ground-truth project."""

from pathlib import Path
import os

try:
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).resolve().parents[1] / ".env")
except ImportError:
    pass

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
RAW = DATA / "raw"
PROCESSED = DATA / "processed"

FIRMS_RAW = RAW / "firms"
CALFIRE_RAW = RAW / "calfire"
FPAFOD_RAW = RAW / "fpafod"

FIRMS_MAP_KEY = os.environ.get("FIRMS_MAP_KEY")

# California bounding box (W, S, E, N)
CA_BBOX = (-124.55, 32.50, -114.10, 42.05)

# Fire season window: Jun 1 – Nov 30, 2020
SEASON_START = "2020-06-01"
SEASON_END = "2020-11-30"

# FIRMS source for archived VIIRS Suomi-NPP. Use _NRT for recent (last ~2 months),
# _SP (standard processing) for archived. 2020 is archived.
FIRMS_SOURCE = "VIIRS_SNPP_SP"

FIRMS_AREA_URL = (
    "https://firms.modaps.eosdis.nasa.gov/api/area/csv/"
    "{key}/{source}/{w},{s},{e},{n}/{day_range}/{date}"
)
