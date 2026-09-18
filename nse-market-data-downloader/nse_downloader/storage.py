"""
CSV storage for NSE market data.

Handles file naming, directory creation, and idempotent writes
(same-day re-runs overwrite the file rather than creating duplicates).
"""

import logging
from datetime import date, datetime
from pathlib import Path
from typing import Optional

import pandas as pd

from nse_downloader.config import CSV_DATE_FORMAT, DEFAULT_OUTPUT_DIR

logger = logging.getLogger(__name__)


class StorageError(Exception):
    """Raised when data storage fails."""


class CSVStorage:
    """Persists DataFrames to date-stamped CSV files."""

    def __init__(self, output_dir: Optional[Path] = None) -> None:
        self._output_dir = output_dir or DEFAULT_OUTPUT_DIR

    @property
    def output_dir(self) -> Path:
        return self._output_dir

    def save(
        self,
        df: pd.DataFrame,
        csv_prefix: str,
        target_date: Optional[date] = None,
    ) -> Path:
        """Save a DataFrame to a CSV file.

        File naming convention: ``{csv_prefix}_{YYYY-MM-DD}.csv``

        If a file for the same prefix and date already exists, it is
        **overwritten** (idempotent) — this avoids confusing duplicate
        files when the downloader is run multiple times on the same day.

        Args:
            df: The validated DataFrame to persist.
            csv_prefix: Prefix for the CSV filename (e.g. ``top_gainers``).
            target_date: The date to stamp the file with. Defaults to today.

        Returns:
            Path to the saved CSV file.

        Raises:
            StorageError: If the file cannot be written.
        """
        if target_date is None:
            target_date = date.today()

        date_str = target_date.strftime(CSV_DATE_FORMAT)
        filename = f"{csv_prefix}_{date_str}.csv"
        filepath = self._output_dir / filename

        try:
            # Create output directory if it doesn't exist
            self._output_dir.mkdir(parents=True, exist_ok=True)

            # Write CSV — overwrites if file already exists (idempotent)
            df.to_csv(filepath, index=False, encoding="utf-8")

            logger.info(
                "Saved %d records to %s (%.1f KB)",
                len(df),
                filepath,
                filepath.stat().st_size / 1024,
            )
            return filepath

        except OSError as exc:
            raise StorageError(
                f"Failed to write CSV to {filepath}: {exc}"
            ) from exc
        except Exception as exc:
            raise StorageError(
                f"Unexpected error saving CSV {filepath}: {exc}"
            ) from exc
