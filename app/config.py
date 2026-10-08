import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

DATA_DIR = Path(os.environ.get("TOUR_DATA_DIR", "var")).resolve()
TRIPS_DIR = DATA_DIR / "trips"
CACHE_PATH = DATA_DIR / "cache.sqlite"
TOURS_DIR = Path(os.environ.get("TOUR_GUIDES_DIR", "tours")).resolve()
