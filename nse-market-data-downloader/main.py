#!/usr/bin/env python3


import argparse
import logging
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path

from nse_downloader.config import (
    ALL_DATASET_KEYS,
    DATASETS,
    DEFAULT_OUTPUT_DIR,
    LOG_DIR,
    LOG_FILE,
    PAGE_TO_DATASETS,
)
from nse_downloader.downloader import NSEDownloader


def setup_logging(verbose: bool = False) -> None:
    """Configure logging to console and rotating log file."""
    log_level = logging.DEBUG if verbose else logging.INFO

    # Create log directory
    LOG_DIR.mkdir(parents=True, exist_ok=True)

    # Root logger
    root_logger = logging.getLogger()
    root_logger.setLevel(logging.DEBUG)

    # Console handler — INFO level (or DEBUG if verbose)
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(log_level)
    console_fmt = logging.Formatter(
        "%(asctime)s [%(levelname)-7s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    console_handler.setFormatter(console_fmt)

    # File handler — DEBUG level, rotating at 5 MB
    file_handler = RotatingFileHandler(
        LOG_FILE,
        maxBytes=5 * 1024 * 1024,  # 5 MB
        backupCount=3,
        encoding="utf-8",
    )
    file_handler.setLevel(logging.DEBUG)
    file_fmt = logging.Formatter(
        "%(asctime)s [%(levelname)-7s] %(name)s:%(lineno)d — %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    file_handler.setFormatter(file_fmt)

    root_logger.addHandler(console_handler)
    root_logger.addHandler(file_handler)


def resolve_dataset_keys(raw_keys: list[str]) -> list[str]:
    
    resolved = []
    for key in raw_keys:
        if key in DATASETS:
            resolved.append(key)
        elif key in PAGE_TO_DATASETS:
            resolved.extend(PAGE_TO_DATASETS[key])
        else:
            logging.error(
                "Unknown dataset: '%s'. Use --list-datasets to see options.",
                key,
            )
            sys.exit(2)
    return resolved


def list_datasets() -> None:
    """Print available datasets and exit."""
    print("\nAvailable datasets:\n")
    print(f"  {'Key':<25} {'Name':<35} {'CSV Prefix'}")
    print(f"  {'---':<25} {'----':<35} {'----------'}")
    for key, ds in DATASETS.items():
        print(f"  {key:<25} {ds.name:<35} {ds.csv_prefix}")

    print(f"\nPage aliases (expand to multiple datasets):\n")
    for page, keys in PAGE_TO_DATASETS.items():
        print(f"  {page:<35} → {', '.join(keys)}")
    print()


def build_parser() -> argparse.ArgumentParser:
    """Build the CLI argument parser."""
    parser = argparse.ArgumentParser(
        prog="nse-downloader",
        description=(
            "Download and store CSV data from NSE India market data pages."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Examples:\n"
            "  python main.py                                  "
            "# Download all datasets\n"
            "  python main.py --dataset top-gainers            "
            "# Single dataset\n"
            "  python main.py --dataset top-gainers top-losers "
            "# Multiple datasets\n"
            "  python main.py --dataset top-gainers-losers     "
            "# Page alias → gainers + losers\n"
            "  python main.py --output-dir ./my_data           "
            "# Custom output\n"
            "  python main.py --schedule 30                    "
            "# Repeat every 30 min\n"
            "  python main.py --list-datasets                  "
            "# Show available datasets\n"
        ),
    )
    parser.add_argument(
        "--dataset",
        nargs="+",
        metavar="KEY",
        help="Dataset key(s) or page alias(es) to download. "
             "Omit to download all.",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=DEFAULT_OUTPUT_DIR,
        metavar="DIR",
        help=f"Output directory for CSV files (default: {DEFAULT_OUTPUT_DIR})",
    )
    parser.add_argument(
        "--schedule",
        type=int,
        metavar="MINUTES",
        help="Run on a recurring schedule every N minutes.",
    )
    parser.add_argument(
        "--list-datasets",
        action="store_true",
        help="List all available datasets and exit.",
    )
    parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="Enable verbose (DEBUG) logging.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    """Main entry point. Returns exit code (0/1/2)."""
    parser = build_parser()
    args = parser.parse_args(argv)

    # --list-datasets
    if args.list_datasets:
        list_datasets()
        return 0

    # Set up logging
    setup_logging(verbose=args.verbose)
    logger = logging.getLogger(__name__)

    # Resolve datasets
    if args.dataset:
        dataset_keys = resolve_dataset_keys(args.dataset)
    else:
        dataset_keys = ALL_DATASET_KEYS

    logger.info("=" * 60)
    logger.info("NSE Market Data Downloader")
    logger.info("Datasets: %s", ", ".join(dataset_keys))
    logger.info("Output directory: %s", args.output_dir)
    logger.info("=" * 60)

    # Scheduled execution
    if args.schedule:
        from nse_downloader.scheduler import DownloadScheduler

        scheduler = DownloadScheduler(
            interval_minutes=args.schedule,
            dataset_keys=dataset_keys,
            output_dir=args.output_dir,
        )
        scheduler.start()
        return 0

    # Single execution
    downloader = NSEDownloader(output_dir=args.output_dir)
    summary = downloader.download(dataset_keys)

    # Print results table
    print("\n" + "=" * 70)
    print(f"{'Dataset':<25} {'Status':<10} {'Records':<10} {'File'}")
    print("-" * 70)
    for result in summary.results:
        status = "✓ OK" if result.success else "✗ FAIL"
        records = str(result.record_count) if result.success else "-"
        filepath = result.filepath.name if result.filepath else (
            result.error[:40] if result.error else "N/A"
        )
        print(f"  {result.dataset_key:<23} {status:<10} {records:<10} {filepath}")
    print("=" * 70)
    print(
        f"Total: {summary.successful}/{summary.total_datasets} succeeded, "
        f"{summary.failed} failed\n"
    )

    # Exit codes
    if summary.all_succeeded:
        return 0
    elif summary.all_failed:
        return 2
    else:
        return 1


if __name__ == "__main__":
    sys.exit(main())
