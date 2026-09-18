"""
Scheduler for periodic execution of the NSE data downloader.

Provides optional recurring downloads at a configurable interval,
useful for automated data collection during trading hours.
"""

import logging
import signal
import sys
from pathlib import Path
from typing import List, Optional

import schedule
import time

from nse_downloader.downloader import NSEDownloader

logger = logging.getLogger(__name__)


class DownloadScheduler:
    """Runs the NSE downloader on a recurring schedule."""

    def __init__(
        self,
        interval_minutes: int,
        dataset_keys: Optional[List[str]] = None,
        output_dir: Optional[Path] = None,
    ) -> None:
        self._interval = interval_minutes
        self._dataset_keys = dataset_keys
        self._output_dir = output_dir
        self._running = True

        # Register signal handlers for graceful shutdown
        signal.signal(signal.SIGINT, self._handle_signal)
        signal.signal(signal.SIGTERM, self._handle_signal)

    def _handle_signal(self, signum: int, frame: object) -> None:
        """Handle shutdown signals gracefully."""
        logger.info("Received signal %d — shutting down scheduler...", signum)
        self._running = False

    def _run_download(self) -> None:
        """Execute a single download run."""
        logger.info("Scheduled download starting...")
        try:
            downloader = NSEDownloader(output_dir=self._output_dir)
            if self._dataset_keys:
                summary = downloader.download(self._dataset_keys)
            else:
                summary = downloader.download_all()

            logger.info(
                "Scheduled run complete: %d/%d succeeded",
                summary.successful,
                summary.total_datasets,
            )
        except Exception as exc:
            logger.error(
                "Scheduled run failed: %s: %s",
                type(exc).__name__,
                exc,
                exc_info=True,
            )

    def start(self) -> None:
        """Start the scheduler and run indefinitely until stopped."""
        logger.info(
            "Starting scheduler: running every %d minute(s)",
            self._interval,
        )

        # Run immediately on start
        self._run_download()

        # Schedule recurring runs
        schedule.every(self._interval).minutes.do(self._run_download)

        while self._running:
            schedule.run_pending()
            time.sleep(1)

        logger.info("Scheduler stopped.")
