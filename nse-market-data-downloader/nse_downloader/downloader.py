"""
Orchestrator for NSE market data downloads.

Coordinates the fetch → validate → store pipeline for each dataset,
with failure isolation so one dataset's failure doesn't block others.
"""

import logging
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Dict, List, Optional

from nse_downloader.client import NSEClient, NSEClientError
from nse_downloader.config import ALL_DATASET_KEYS, DATASETS, DatasetConfig
from nse_downloader.db import DatabaseStorage
from nse_downloader.notifications import send_failure_notification
from nse_downloader.storage import CSVStorage, StorageError
from nse_downloader.validator import (
    DataValidator,
    ValidationError,
    ValidationReport,
)

logger = logging.getLogger(__name__)


@dataclass
class DownloadResult:
    """Result of downloading a single dataset."""

    dataset_key: str
    success: bool
    filepath: Optional[Path] = None
    record_count: int = 0
    error: Optional[str] = None
    validation_report: Optional[ValidationReport] = None


@dataclass
class DownloadSummary:
    """Summary of all download operations in a run."""

    results: List[DownloadResult] = field(default_factory=list)
    total_datasets: int = 0
    successful: int = 0
    failed: int = 0

    @property
    def all_succeeded(self) -> bool:
        return self.failed == 0

    @property
    def all_failed(self) -> bool:
        return self.successful == 0 and self.total_datasets > 0


class NSEDownloader:
    """Orchestrates the download pipeline for NSE market data.

    Usage::

        downloader = NSEDownloader(output_dir=Path("data"))
        summary = downloader.download_all()
        # or
        summary = downloader.download(["top-gainers", "52-week-high"])
    """

    def __init__(
        self,
        output_dir: Optional[Path] = None,
        client: Optional[NSEClient] = None,
    ) -> None:
        self._client = client or NSEClient()
        self._validator = DataValidator()
        self._storage = CSVStorage(output_dir=output_dir)
        
        # Determine db path based on output_dir
        db_path = (output_dir or Path("data")) / "market_data.db"
        self._db_storage = DatabaseStorage(db_path=db_path)

    def download_all(self) -> DownloadSummary:
        """Download all configured datasets.

        Returns:
            Summary of download results.
        """
        return self.download(ALL_DATASET_KEYS)

    def download(
        self,
        dataset_keys: List[str],
        target_date: Optional[date] = None,
    ) -> DownloadSummary:
        """Download specified datasets.

        Failure in one dataset does NOT prevent others from being
        downloaded — each dataset is processed independently.

        Args:
            dataset_keys: List of dataset keys to download.
            target_date: Date to stamp CSV files with. Defaults to today.

        Returns:
            Summary of download results.
        """
        summary = DownloadSummary(total_datasets=len(dataset_keys))

        logger.info(
            "Starting download of %d dataset(s): %s",
            len(dataset_keys),
            ", ".join(dataset_keys),
        )

        with self._client:
            for key in dataset_keys:
                result = self._download_single(key, target_date)
                summary.results.append(result)

                if result.success:
                    summary.successful += 1
                else:
                    summary.failed += 1

        # Log summary
        logger.info(
            "Download complete: %d/%d succeeded, %d failed",
            summary.successful,
            summary.total_datasets,
            summary.failed,
        )

        if summary.failed > 0:
            failed_keys = [
                r.dataset_key for r in summary.results if not r.success
            ]
            logger.warning("Failed datasets: %s", ", ".join(failed_keys))

        return summary

    def _download_single(
        self,
        dataset_key: str,
        target_date: Optional[date] = None,
    ) -> DownloadResult:
        """Download a single dataset through the full pipeline.

        Catches all exceptions to ensure failure isolation.
        """
        # Resolve dataset config
        dataset = DATASETS.get(dataset_key)
        if dataset is None:
            logger.error("Unknown dataset key: '%s'", dataset_key)
            return DownloadResult(
                dataset_key=dataset_key,
                success=False,
                error=f"Unknown dataset key: '{dataset_key}'. "
                       f"Available: {', '.join(ALL_DATASET_KEYS)}",
            )

        logger.info("--- Downloading: %s ---", dataset.name)

        try:
            # 1. Fetch raw data from NSE API
            raw_data = self._client.fetch(dataset)

            # 2. Validate and clean
            df, report = self._validator.validate(raw_data, dataset)

            # 3. Store as CSV
            filepath = self._storage.save(
                df, dataset.csv_prefix, target_date
            )

            # 4. Store in SQLite Database for Historical tracking
            self._db_storage.save_dataframe(
                df, dataset.csv_prefix, target_date or date.today()
            )

            logger.info(
                "✓ %s: %d records saved to %s (and DB)",
                dataset.name,
                report.valid_record_count,
                filepath,
            )

            return DownloadResult(
                dataset_key=dataset_key,
                success=True,
                filepath=filepath,
                record_count=report.valid_record_count,
                validation_report=report,
            )

        except NSEClientError as exc:
            logger.error("✗ %s: Fetch failed — %s", dataset.name, exc)
            send_failure_notification(dataset.name, f"Fetch failed: {exc}")
            return DownloadResult(
                dataset_key=dataset_key,
                success=False,
                error=f"Fetch failed: {exc}",
            )

        except ValidationError as exc:
            logger.error("✗ %s: Validation failed — %s", dataset.name, exc)
            send_failure_notification(dataset.name, f"Validation failed: {exc}")
            return DownloadResult(
                dataset_key=dataset_key,
                success=False,
                error=f"Validation failed: {exc}",
            )

        except StorageError as exc:
            logger.error("✗ %s: Storage failed — %s", dataset.name, exc)
            send_failure_notification(dataset.name, f"Storage failed: {exc}")
            return DownloadResult(
                dataset_key=dataset_key,
                success=False,
                error=f"Storage failed: {exc}",
            )

        except Exception as exc:
            logger.error(
                "✗ %s: Unexpected error — %s: %s",
                dataset.name,
                type(exc).__name__,
                exc,
                exc_info=True,
            )
            send_failure_notification(dataset.name, f"Unexpected error: {type(exc).__name__}")
            return DownloadResult(
                dataset_key=dataset_key,
                success=False,
                error=f"Unexpected error: {type(exc).__name__}: {exc}",
            )
