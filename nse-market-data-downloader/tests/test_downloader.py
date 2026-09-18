"""
Tests for the download orchestrator.

Tests the full pipeline with mocked client, ensuring failure isolation
and correct result reporting.
"""

from datetime import date
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from nse_downloader.client import NSEClientError
from nse_downloader.downloader import NSEDownloader
from nse_downloader.validator import ValidationError


@pytest.fixture
def tmp_output_dir(tmp_path):
    return tmp_path / "output"


# --- Per-dataset mock responses matching real NSE API shapes ---

GAINERS_RESPONSE = {
    "NIFTY": {
        "data": [
            {"symbol": "TCS", "ltp": 3500.0, "pChange": 6.06},
            {"symbol": "INFY", "ltp": 1400.0, "pChange": 1.45},
        ],
        "metadata": {}
    },
    "legends": [["NIFTY", "NIFTY 50"]],
}

LOOSERS_RESPONSE = {
    "NIFTY": {
        "data": [
            {"symbol": "ZOMATO", "ltp": 260.0, "pChange": -5.10},
        ],
    },
    "legends": [["NIFTY", "NIFTY 50"]],
}

PRICE_BAND_RESPONSE = {
    "upper": {
        "All Securities": {
            "data": [
                {"symbol": "KPIT", "series": "EQ", "ltp": 1590.0, "pChange": 5.01},
            ]
        }
    },
    "lower": {"All Securities": {"data": []}},
    "both": {"All Securities": {"data": []}},
}

VOLUME_RESPONSE = {
    "data": [
        {"symbol": "SUZLON", "ltp": 58.5, "pChange": 12.5},
        {"symbol": "NHPC", "ltp": 92.0, "pChange": 7.8},
    ]
}

WEEK52_RESPONSE = {
    "dataLtpGreater20": [
        {"symbol": "TRENT", "ltp": 5870.0, "pChange": 4.43},
    ],
    "dataLtpLess20": [
        {"symbol": "XYZ", "ltp": 15.0, "pChange": 3.0},
    ],
}

# Map dataset key → response shape
_MOCK_RESPONSES = {
    "top-gainers": GAINERS_RESPONSE,
    "top-losers": LOOSERS_RESPONSE,
    "upper-band-hitters": PRICE_BAND_RESPONSE,
    "volume-gainers": VOLUME_RESPONSE,
    "52-week-high": WEEK52_RESPONSE,
}


def _make_valid_response(dataset_key: str = "volume-gainers"):
    """Create a valid API response for the given dataset key."""
    return _MOCK_RESPONSES.get(dataset_key, VOLUME_RESPONSE)


class TestSuccessfulDownload:
    """Tests for successful download scenarios."""

    @patch("nse_downloader.downloader.NSEClient")
    def test_download_all_datasets(self, mock_client_cls, tmp_output_dir):
        """Should successfully download all datasets."""
        mock_client = MagicMock()
        mock_client_cls.return_value = mock_client
        # Return dataset-specific response for each fetch call
        from nse_downloader.config import ALL_DATASET_KEYS
        mock_client.fetch.side_effect = [
            _make_valid_response(k) for k in ALL_DATASET_KEYS
        ]
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)

        downloader = NSEDownloader(
            output_dir=tmp_output_dir, client=mock_client
        )
        summary = downloader.download_all()

        assert summary.total_datasets == 5  # all 5 datasets
        assert summary.successful == 5
        assert summary.failed == 0
        assert summary.all_succeeded

    @patch("nse_downloader.downloader.NSEClient")
    def test_download_single_dataset(self, mock_client_cls, tmp_output_dir):
        """Should download a single specified dataset."""
        mock_client = MagicMock()
        mock_client_cls.return_value = mock_client
        mock_client.fetch.return_value = _make_valid_response("top-gainers")
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)

        downloader = NSEDownloader(
            output_dir=tmp_output_dir, client=mock_client
        )
        summary = downloader.download(["top-gainers"])

        assert summary.total_datasets == 1
        assert summary.successful == 1
        assert summary.results[0].success
        assert summary.results[0].record_count == 2

    @patch("nse_downloader.downloader.NSEClient")
    def test_csv_files_created(self, mock_client_cls, tmp_output_dir):
        """Should create CSV files on disk."""
        mock_client = MagicMock()
        mock_client_cls.return_value = mock_client
        mock_client.fetch.return_value = _make_valid_response("top-gainers")
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)

        downloader = NSEDownloader(
            output_dir=tmp_output_dir, client=mock_client
        )
        summary = downloader.download(
            ["top-gainers"], target_date=date(2026, 9, 18)
        )

        assert summary.results[0].filepath is not None
        assert summary.results[0].filepath.exists()
        assert "top_gainers_2026-09-18" in summary.results[0].filepath.name


class TestFailureIsolation:
    """Tests for failure isolation between datasets."""

    @patch("nse_downloader.downloader.NSEClient")
    def test_one_failure_doesnt_block_others(
        self, mock_client_cls, tmp_output_dir
    ):
        """Failure in one dataset should not prevent others from downloading."""
        mock_client = MagicMock()
        mock_client_cls.return_value = mock_client
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)

        # First call fails, second succeeds
        mock_client.fetch.side_effect = [
            NSEClientError("Network error"),
            _make_valid_response("top-losers"),
        ]

        downloader = NSEDownloader(
            output_dir=tmp_output_dir, client=mock_client
        )
        summary = downloader.download(["top-gainers", "top-losers"])

        assert summary.total_datasets == 2
        assert summary.successful == 1
        assert summary.failed == 1

        # First failed, second succeeded
        assert not summary.results[0].success
        assert summary.results[1].success

    @patch("nse_downloader.downloader.NSEClient")
    def test_all_failures_reported(self, mock_client_cls, tmp_output_dir):
        """All failures should be reported in the summary."""
        mock_client = MagicMock()
        mock_client_cls.return_value = mock_client
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_client.fetch.side_effect = NSEClientError("Total failure")

        downloader = NSEDownloader(
            output_dir=tmp_output_dir, client=mock_client
        )
        summary = downloader.download(
            ["top-gainers", "top-losers", "volume-gainers"]
        )

        assert summary.total_datasets == 3
        assert summary.failed == 3
        assert summary.all_failed


class TestUnknownDataset:
    """Tests for unknown dataset keys."""

    @patch("nse_downloader.downloader.NSEClient")
    def test_unknown_key_returns_error(self, mock_client_cls, tmp_output_dir):
        """Unknown dataset key should return a failed result."""
        mock_client = MagicMock()
        mock_client_cls.return_value = mock_client
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)

        downloader = NSEDownloader(
            output_dir=tmp_output_dir, client=mock_client
        )
        summary = downloader.download(["nonexistent-dataset"])

        assert summary.failed == 1
        assert "Unknown dataset key" in summary.results[0].error


class TestValidationFailure:
    """Tests for validation-stage failures."""

    @patch("nse_downloader.downloader.NSEClient")
    def test_empty_response_fails_validation(
        self, mock_client_cls, tmp_output_dir
    ):
        """Empty response should fail validation."""
        mock_client = MagicMock()
        mock_client_cls.return_value = mock_client
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_client.fetch.return_value = {"data": []}

        downloader = NSEDownloader(
            output_dir=tmp_output_dir, client=mock_client
        )
        summary = downloader.download(["top-gainers"])

        assert summary.failed == 1
        assert "Validation failed" in summary.results[0].error
