# NSE Market Data Downloader

A production-minded Python CLI application that automatically downloads and stores CSV data from NSE India's market data pages.

## What It Does

This application retrieves live market data from four NSE India pages and saves each dataset as a date-stamped CSV file:

| Dataset | NSE Page | CSV Prefix |
|:---|:---|:---|
| Top Gainers | [Top Gainers / Losers](https://www.nseindia.com/market-data/top-gainers-losers) | `top_gainers` |
| Top Losers | [Top Gainers / Losers](https://www.nseindia.com/market-data/top-gainers-losers) | `top_losers` |
| Upper Band Hitters | [Upper Band Hitters](https://www.nseindia.com/market-data/upper-band-hitters) | `upper_band_hitters` |
| Volume Gainers | [Volume Gainers / Spurts](https://www.nseindia.com/market-data/volume-gainers-spurts) | `volume_gainers` |
| 52 Week High | [52 Week High — Equity Market](https://www.nseindia.com/market-data/52-week-high-equity-market) | `52_week_high` |

## Installation

### Prerequisites

- Python 3.10 or higher

### Setup

```bash
# Clone or download the project
cd nse-market-data-downloader

# Install dependencies
pip install -r requirements.txt
```

### Docker (Alternative)

```bash
# Build the image
docker build -t nse-downloader .

# Run
docker run --rm -v $(pwd)/data:/app/data nse-downloader

# Download specific dataset
docker run --rm -v $(pwd)/data:/app/data nse-downloader --dataset top-gainers
```

## How to Run

### Download All Datasets

```bash
python3 main.py
```

### Download Specific Dataset(s)

```bash
# Single dataset
python3 main.py --dataset top-gainers

# Multiple datasets
python3 main.py --dataset top-gainers top-losers volume-gainers

# Use page alias (downloads both gainers AND losers)
python3 main.py --dataset top-gainers-losers
```

### Custom Output Directory

```bash
python3 main.py --output-dir ./my_data
```

### Scheduled Execution (Bonus)

```bash
# Run every 30 minutes
python3 main.py --schedule 30
```

### List Available Datasets

```bash
python3 main.py --list-datasets
```

### Verbose Logging

```bash
python3 main.py -v
```

## Architecture

The application follows a clean separation of responsibilities:

```
nse-market-data-downloader/
├── main.py                      # CLI entry point (argparse, logging)
├── nse_downloader/
│   ├── config.py                # All configuration: URLs, columns, settings
│   ├── client.py                # HTTP client: sessions, retries, rate limiting
│   ├── validator.py             # Data validation: structure, columns, dedup
│   ├── storage.py               # CSV storage: naming, directories, idempotency
│   ├── downloader.py            # Orchestrator: fetch → validate → store
│   └── scheduler.py             # Scheduled/recurring execution
├── tests/                       # 58 unit tests across 5 test modules
├── data/sample/                 # Sample CSV outputs
├── Dockerfile                   # Docker support
├── requirements.txt
└── pyproject.toml
```

### Pipeline Flow

```
CLI Input → Orchestrator → HTTP Client → Validator → CSV Storage
                              │                          │
                         NSE API ←──                  data/*.csv
```

Each dataset flows through: **Fetch → Validate → Store**. Failures at any stage are caught and isolated — one dataset failing never blocks the others.

## How Data Acquisition Works

1. **Session Initialization**: The HTTP client creates a `requests.Session` and hits `https://www.nseindia.com` to acquire session cookies (required by NSE's anti-bot protections).

2. **API Requests**: For each dataset, the client sends a GET request to NSE's internal JSON API (e.g., `/api/live-analysis/gainers/allSec`) with browser-like headers (`User-Agent`, `Referer`, `Accept`).

3. **Rate Limiting**: A configurable delay (default: 1.5s) is enforced between API requests to avoid being IP-blocked.

4. **Retry with Backoff**: Failed requests are retried up to 3 times with exponential backoff (2s → 4s → 8s). HTTP 429/5xx responses trigger automatic retries via `urllib3.Retry`.

5. **Session Refresh**: If a 401 or 403 is received (cookie expiry), the session is automatically refreshed by re-hitting the homepage.

## Where Files Are Stored

CSV files are saved to the `data/` directory (configurable via `--output-dir`):

```
data/
├── top_gainers_2026-09-18.csv
├── top_losers_2026-09-18.csv
├── upper_band_hitters_2026-09-18.csv
├── volume_gainers_2026-09-18.csv
├── 52_week_high_2026-09-18.csv
└── sample/                        # Sample outputs for reference
```

Log files are saved to `logs/nse_downloader.log` (rotating, max 5 MB).

## How Errors Are Handled

| Error Type | Handling |
|:---|:---|
| **Network failure / Timeout** | Retried up to 3 times with exponential backoff |
| **HTTP 401/403** | Session cookies refreshed, then retried |
| **HTTP 429/5xx** | Automatic retry via `urllib3.Retry` adapter |
| **Invalid JSON response** | `NSEClientError` raised, dataset marked as failed |
| **Empty data** | `ValidationError` raised, dataset marked as failed |
| **Missing columns** | Warning if < 50% missing; error if ≥ 50% |
| **One dataset fails** | Other datasets continue downloading independently |
| **File write failure** | `StorageError` raised, logged with details |

All errors are logged with timestamps, dataset names, and error messages. The application uses structured exit codes:
- `0`: All datasets downloaded successfully
- `1`: Partial success (some datasets failed)
- `2`: Total failure (all datasets failed)

## How Duplicate Data Is Handled

**Idempotent overwrites**: Running the downloader twice on the same day produces the same file (`top_gainers_2026-09-18.csv`), not a duplicate. The second run **overwrites** the first — keeping the data directory clean and producing consistent results.

**Row-level deduplication**: Before saving, the validator removes duplicate rows by `symbol` (keeping the first occurrence).

## How Tests Are Run

```bash
# Run all tests
python3 -m pytest tests/ -v

# Run with coverage report
python3 -m pytest tests/ -v --cov=nse_downloader --cov-report=term-missing

# Run a specific test module
python3 -m pytest tests/test_validator.py -v

# Run a specific test class
python3 -m pytest tests/test_client.py::TestNSEClientFetch -v
```

### Test Coverage

| Module | Coverage | Tests |
|:---|:---|:---|
| `config.py` | 100% | — |
| `client.py` | 93% | 8 tests |
| `validator.py` | 89% | 12 tests |
| `storage.py` | 83% | 11 tests |
| `downloader.py` | 92% | 7 tests |
| `main.py` | — | 14 tests |
| `scheduler.py` | 0%* | — |
| **Total** | **81%** | **58 tests** |

*Scheduler is a bonus module; it depends on real-time signal handling which is hard to unit-test without integration tests.

### What's Tested

- ✅ Successful download with mocked HTTP responses
- ✅ Failed request (timeout, connection error, HTTP errors)
- ✅ Invalid/empty response handling
- ✅ Data validation (columns, structure, dedup)
- ✅ CSV file creation and content
- ✅ Idempotent overwrite (duplicate handling)
- ✅ Session cookie management and refresh on 403
- ✅ Retry with exponential backoff
- ✅ CLI argument parsing and dataset resolution
- ✅ Exit code semantics (0/1/2)
- ✅ Unknown dataset key handling
- ✅ Failure isolation between datasets

## Configuration

All configuration is centralized in [`nse_downloader/config.py`](nse_downloader/config.py):

- **API endpoints** for all 5 datasets
- **Expected columns** per dataset (for validation)
- **HTTP headers** (User-Agent, Referer, etc.)
- **Timeout**: 30 seconds (configurable)
- **Max retries**: 3 (configurable)
- **Backoff factor**: 2x exponential
- **Rate limit delay**: 1.5 seconds between requests
- **Output directory**: `data/` (configurable via CLI)

To modify settings, edit `config.py` — no code changes needed elsewhere.

## Limitations & Assumptions

1. **Unofficial API**: NSE does not provide an official public API. This application uses internal JSON endpoints discovered from the website's network traffic. These endpoints may change without notice — the config-driven design makes updates easy.

2. **Anti-bot Protection**: NSE uses Cloudflare and session-based protections. The application handles this via session cookies and browser-like headers, but aggressive use may result in IP blocking.

3. **Market Hours**: Data reflects live market state. For end-of-day snapshots, run the application after market close (3:30 PM IST).

4. **Rate Limiting**: Built-in 1.5s delay between requests. Reduce this at your own risk.

5. **No Historical Backfill**: The application downloads current-day data. It does not backfill historical data (NSE does not serve historical data via these endpoints).

## Bonus Features

- ✅ **Scheduled execution** (`--schedule 30`) — recurring downloads with graceful shutdown
- ✅ **Retry with exponential backoff** — configurable max retries and backoff factor
- ✅ **Configurable output directory** (`--output-dir`)
- ✅ **Docker** support with Dockerfile
- ✅ **Clean, extensible architecture** — add a new dataset by adding one entry to `config.py`
- ✅ **Good test coverage** — 58 tests, 81% coverage
