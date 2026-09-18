"""
Tests for the CLI entry point.

Covers argument parsing, --list-datasets, and exit codes.
"""

from unittest.mock import MagicMock, patch

import pytest

from main import build_parser, list_datasets, main, resolve_dataset_keys


class TestArgumentParsing:
    """Tests for CLI argument parsing."""

    def test_default_args(self):
        """Default args should download all datasets."""
        parser = build_parser()
        args = parser.parse_args([])

        assert args.dataset is None
        assert args.schedule is None
        assert args.list_datasets is False
        assert args.verbose is False

    def test_single_dataset(self):
        """Should parse a single dataset."""
        parser = build_parser()
        args = parser.parse_args(["--dataset", "top-gainers"])

        assert args.dataset == ["top-gainers"]

    def test_multiple_datasets(self):
        """Should parse multiple datasets."""
        parser = build_parser()
        args = parser.parse_args(
            ["--dataset", "top-gainers", "top-losers", "volume-gainers"]
        )

        assert args.dataset == ["top-gainers", "top-losers", "volume-gainers"]

    def test_output_dir(self):
        """Should parse custom output directory."""
        parser = build_parser()
        args = parser.parse_args(["--output-dir", "./my_data"])

        assert str(args.output_dir) == "my_data"

    def test_schedule_interval(self):
        """Should parse schedule interval."""
        parser = build_parser()
        args = parser.parse_args(["--schedule", "30"])

        assert args.schedule == 30

    def test_verbose_flag(self):
        """Should parse verbose flag."""
        parser = build_parser()
        args = parser.parse_args(["--verbose"])
        assert args.verbose is True

        args2 = parser.parse_args(["-v"])
        assert args2.verbose is True

    def test_list_datasets_flag(self):
        """Should parse list-datasets flag."""
        parser = build_parser()
        args = parser.parse_args(["--list-datasets"])
        assert args.list_datasets is True


class TestDatasetResolution:
    """Tests for dataset key resolution."""

    def test_direct_dataset_key(self):
        """Direct dataset keys should resolve to themselves."""
        result = resolve_dataset_keys(["top-gainers"])
        assert result == ["top-gainers"]

    def test_page_alias_expansion(self):
        """Page aliases should expand to their constituent datasets."""
        result = resolve_dataset_keys(["top-gainers-losers"])
        assert result == ["top-gainers", "top-losers"]

    def test_unknown_key_exits(self):
        """Unknown keys should cause sys.exit."""
        with pytest.raises(SystemExit):
            resolve_dataset_keys(["nonexistent"])


class TestListDatasets:
    """Tests for --list-datasets."""

    def test_list_datasets_returns_zero(self):
        """--list-datasets should return exit code 0."""
        exit_code = main(["--list-datasets"])
        assert exit_code == 0


class TestExitCodes:
    """Tests for main() exit codes."""

    @patch("main.NSEDownloader")
    def test_all_success_returns_zero(self, mock_downloader_cls):
        """All datasets succeeding should return exit code 0."""
        mock_downloader = MagicMock()
        mock_downloader_cls.return_value = mock_downloader

        mock_summary = MagicMock()
        mock_summary.all_succeeded = True
        mock_summary.all_failed = False
        mock_summary.successful = 1
        mock_summary.total_datasets = 1
        mock_summary.failed = 0
        mock_summary.results = [
            MagicMock(
                dataset_key="top-gainers",
                success=True,
                record_count=10,
                filepath=MagicMock(name="top_gainers_2026-09-18.csv"),
            )
        ]
        mock_downloader.download.return_value = mock_summary

        exit_code = main(["--dataset", "top-gainers"])
        assert exit_code == 0

    @patch("main.NSEDownloader")
    def test_all_failed_returns_two(self, mock_downloader_cls):
        """All datasets failing should return exit code 2."""
        mock_downloader = MagicMock()
        mock_downloader_cls.return_value = mock_downloader

        mock_summary = MagicMock()
        mock_summary.all_succeeded = False
        mock_summary.all_failed = True
        mock_summary.successful = 0
        mock_summary.total_datasets = 1
        mock_summary.failed = 1
        mock_summary.results = [
            MagicMock(
                dataset_key="top-gainers",
                success=False,
                record_count=0,
                filepath=None,
                error="Network error",
            )
        ]
        mock_downloader.download.return_value = mock_summary

        exit_code = main(["--dataset", "top-gainers"])
        assert exit_code == 2

    @patch("main.NSEDownloader")
    def test_partial_failure_returns_one(self, mock_downloader_cls):
        """Partial success should return exit code 1."""
        mock_downloader = MagicMock()
        mock_downloader_cls.return_value = mock_downloader

        mock_summary = MagicMock()
        mock_summary.all_succeeded = False
        mock_summary.all_failed = False
        mock_summary.successful = 1
        mock_summary.total_datasets = 2
        mock_summary.failed = 1
        mock_summary.results = [
            MagicMock(
                dataset_key="top-gainers",
                success=True,
                record_count=10,
                filepath=MagicMock(name="top_gainers_2026-09-18.csv"),
            ),
            MagicMock(
                dataset_key="top-losers",
                success=False,
                record_count=0,
                filepath=None,
                error="Timeout",
            ),
        ]
        mock_downloader.download.return_value = mock_summary

        exit_code = main(["--dataset", "top-gainers", "top-losers"])
        assert exit_code == 1
