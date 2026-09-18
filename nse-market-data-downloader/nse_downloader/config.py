"""
Configuration for NSE Market Data Downloader.

All dataset URLs, expected columns, timeouts, and application settings
are defined here — kept separate from application logic.
"""

from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional


# ---------------------------------------------------------------------------
# NSE session / HTTP defaults
# ---------------------------------------------------------------------------

NSE_BASE_URL = "https://www.nseindia.com"

# Browser-like headers required to pass NSE's anti-bot protections
DEFAULT_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "en-US,en;q=0.9",
    "Accept-Encoding": "gzip, deflate, br",
    "Referer": "https://www.nseindia.com/market-data/top-gainers-losers",
    "Connection": "keep-alive",
}

# ---------------------------------------------------------------------------
# Retry / timeout settings
# ---------------------------------------------------------------------------

REQUEST_TIMEOUT = 30  # seconds
MAX_RETRIES = 3
BACKOFF_FACTOR = 2  # exponential: 2s, 4s, 8s
RATE_LIMIT_DELAY = 1.5  # seconds between API requests

# ---------------------------------------------------------------------------
# Session warm-up pages
# The client visits these pages in order to build a valid cookie jar
# before hitting the API endpoints.  Using specific market-data pages
# (rather than just the homepage) avoids Cloudflare challenge pages.
# ---------------------------------------------------------------------------

SESSION_WARM_UP_URLS = [
    f"{NSE_BASE_URL}/market-data/top-gainers-losers",
]

# ---------------------------------------------------------------------------
# Dataset definitions
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class DatasetConfig:
    """Configuration for a single NSE dataset."""

    key: str            # CLI-friendly identifier
    name: str           # Human-readable name
    api_url: str        # Full API endpoint URL
    referer: str        # Referer header for this specific request
    csv_prefix: str     # Filename prefix for CSV output
    expected_columns: List[str]  # Columns that MUST be present
    # Dot-separated path into JSON response to find the data array.
    # Special token "__first__" means "take the first key of that dict".
    # Examples:
    #   "data"                   →  resp["data"]
    #   "gainers.data"           →  resp["gainers"]["data"]
    #   "upper.__first__.data"   →  resp["upper"][first_key]["data"]
    data_json_path: str = "data"


# ---------------------------------------------------------------------------
# Real API endpoints — discovered directly from NSE's JavaScript sources:
#   /dist/js/sections/live-analysis/top-gainers-loosers.js
#   /dist/js/sections/live-analysis/price-band-hitters.js
#   /dist/js/sections/live-analysis/volume-gainers.js
#   /dist/js/sections/live-analysis/52week-high-low.js
#
# NOTE: NSE spells "losers" as "loosers" in their own API — intentional.
# ---------------------------------------------------------------------------

DATASETS: Dict[str, DatasetConfig] = {
    "top-gainers": DatasetConfig(
        key="top-gainers",
        name="Top Gainers",
        api_url=f"{NSE_BASE_URL}/api/live-analysis-variations?index=gainers",
        referer=f"{NSE_BASE_URL}/market-data/top-gainers-losers",
        csv_prefix="top_gainers",
        # Response shape: {"NIFTY": {"data": [...]}, "legends": [...]}
        data_json_path="NIFTY.data",
        expected_columns=[
            "symbol", "ltp", "pChange",
        ],
    ),
    "top-losers": DatasetConfig(
        key="top-losers",
        name="Top Losers",
        # NSE intentionally spells it "loosers" in their API endpoint
        api_url=f"{NSE_BASE_URL}/api/live-analysis-variations?index=loosers",
        referer=f"{NSE_BASE_URL}/market-data/top-gainers-losers",
        csv_prefix="top_losers",
        data_json_path="NIFTY.data",
        expected_columns=[
            "symbol", "ltp", "pChange",
        ],
    ),
    "upper-band-hitters": DatasetConfig(
        key="upper-band-hitters",
        name="Upper Band Hitters",
        api_url=f"{NSE_BASE_URL}/api/live-analysis-price-band-hitter",
        referer=f"{NSE_BASE_URL}/market-data/upper-band-hitters",
        csv_prefix="upper_band_hitters",
        # Response shape: {"upper": {"All Securities": {"data": [...], ...}}, "lower": {...}}
        data_json_path="upper.__first__.data",
        expected_columns=[
            "symbol", "series", "ltp", "pChange",
        ],
    ),
    "volume-gainers": DatasetConfig(
        key="volume-gainers",
        name="Volume Gainers / Spurts",
        api_url=f"{NSE_BASE_URL}/api/live-analysis-volume-gainers",
        referer=f"{NSE_BASE_URL}/market-data/volume-gainers-spurts",
        csv_prefix="volume_gainers",
        # Response shape: {"data": [...], "timestamp": "..."}
        data_json_path="data",
        expected_columns=[
            "symbol", "ltp", "pChange",
        ],
    ),
    "52-week-high": DatasetConfig(
        key="52-week-high",
        name="52 Week High — Equity Market",
        api_url=f"{NSE_BASE_URL}/api/live-analysis-52Week?index=high",
        referer=f"{NSE_BASE_URL}/market-data/52-week-high-equity-market",
        csv_prefix="52_week_high",
        # Response shape: {"dataLtpGreater20": [...], "dataLtpLess20": [...]}
        # Validator merges both arrays into one DataFrame.
        data_json_path="dataLtpGreater20",
        expected_columns=[
            "symbol", "ltp", "pChange",
        ],
    ),
}

# Mapping from assignment page names to dataset keys for convenience
PAGE_TO_DATASETS = {
    "top-gainers-losers": ["top-gainers", "top-losers"],
    "upper-band-hitters": ["upper-band-hitters"],
    "volume-gainers-spurts": ["volume-gainers"],
    "52-week-high-equity-market": ["52-week-high"],
}

# All dataset keys in download order
ALL_DATASET_KEYS = list(DATASETS.keys())

# ---------------------------------------------------------------------------
# Output / storage settings
# ---------------------------------------------------------------------------

DEFAULT_OUTPUT_DIR = Path("data")
LOG_DIR = Path("logs")
LOG_FILE = LOG_DIR / "nse_downloader.log"
DATE_FORMAT = "%Y-%m-%d"
CSV_DATE_FORMAT = "%Y-%m-%d"
