"""
Tests for CSV storage.

Covers file creation, naming convention, idempotent overwrites,
directory creation, and error handling.
"""

import csv
from datetime import date
from pathlib import Path

import pandas as pd
import pytest

from nse_downloader.storage import CSVStorage, StorageError


@pytest.fixture
def tmp_output_dir(tmp_path):
    """Provide a temporary output directory."""
    return tmp_path / "test_output"


@pytest.fixture
def storage(tmp_output_dir):
    """Create a CSVStorage with temporary directory."""
    return CSVStorage(output_dir=tmp_output_dir)


@pytest.fixture
def sample_df():
    """Create a sample DataFrame for testing."""
    return pd.DataFrame({
        "symbol": ["TCS", "INFY", "WIPRO"],
        "ltp": [3500.0, 1400.0, 450.0],
        "perChange": [2.5, 1.8, -0.5],
    })


class TestCSVFileCreation:
    """Tests for CSV file creation."""

    def test_creates_csv_file(self, storage, sample_df, tmp_output_dir):
        """Should create a CSV file in the output directory."""
        filepath = storage.save(sample_df, "top_gainers", date(2026, 9, 18))

        assert filepath.exists()
        assert filepath.name == "top_gainers_2026-09-18.csv"
        assert filepath.parent == tmp_output_dir

    def test_csv_content_matches_dataframe(self, storage, sample_df):
        """CSV file contents should match the DataFrame."""
        filepath = storage.save(sample_df, "test", date(2026, 1, 1))

        # Read back and compare
        df_read = pd.read_csv(filepath)
        pd.testing.assert_frame_equal(df_read, sample_df)

    def test_csv_has_correct_columns(self, storage, sample_df):
        """CSV should have the correct column headers."""
        filepath = storage.save(sample_df, "test", date(2026, 1, 1))

        with open(filepath) as f:
            reader = csv.reader(f)
            headers = next(reader)
        assert headers == ["symbol", "ltp", "perChange"]

    def test_csv_record_count(self, storage, sample_df):
        """CSV should have the correct number of data rows."""
        filepath = storage.save(sample_df, "test", date(2026, 1, 1))

        df_read = pd.read_csv(filepath)
        assert len(df_read) == 3


class TestFileNaming:
    """Tests for file naming convention."""

    def test_date_format_in_filename(self, storage, sample_df):
        """Filename should contain date in YYYY-MM-DD format."""
        filepath = storage.save(sample_df, "volume_gainers", date(2026, 12, 31))
        assert filepath.name == "volume_gainers_2026-12-31.csv"

    def test_different_prefixes(self, storage, sample_df):
        """Different prefixes should create different files."""
        f1 = storage.save(sample_df, "top_gainers", date(2026, 9, 18))
        f2 = storage.save(sample_df, "top_losers", date(2026, 9, 18))

        assert f1.name != f2.name
        assert f1.exists()
        assert f2.exists()

    def test_uses_today_by_default(self, storage, sample_df):
        """Should use today's date when no date is specified."""
        filepath = storage.save(sample_df, "test")
        today_str = date.today().strftime("%Y-%m-%d")
        assert today_str in filepath.name


class TestIdempotentOverwrite:
    """Tests for duplicate handling / idempotent saves."""

    def test_same_day_overwrites_file(self, storage, tmp_output_dir):
        """Running twice on the same day should overwrite, not duplicate."""
        target_date = date(2026, 9, 18)

        df1 = pd.DataFrame({"symbol": ["TCS"], "ltp": [3500.0]})
        df2 = pd.DataFrame({"symbol": ["INFY"], "ltp": [1400.0]})

        storage.save(df1, "test", target_date)
        filepath = storage.save(df2, "test", target_date)

        # Only one file should exist
        csv_files = list(tmp_output_dir.glob("test_2026-09-18.csv"))
        assert len(csv_files) == 1

        # Content should be from the second write
        df_read = pd.read_csv(filepath)
        assert df_read.iloc[0]["symbol"] == "INFY"

    def test_different_days_create_separate_files(self, storage, sample_df, tmp_output_dir):
        """Different dates should create separate files."""
        storage.save(sample_df, "test", date(2026, 9, 17))
        storage.save(sample_df, "test", date(2026, 9, 18))

        csv_files = list(tmp_output_dir.glob("test_*.csv"))
        assert len(csv_files) == 2


class TestDirectoryCreation:
    """Tests for automatic directory creation."""

    def test_creates_directory_if_missing(self, tmp_path, sample_df):
        """Should create the output directory if it doesn't exist."""
        nested_dir = tmp_path / "deep" / "nested" / "dir"
        storage = CSVStorage(output_dir=nested_dir)

        filepath = storage.save(sample_df, "test", date(2026, 1, 1))

        assert nested_dir.exists()
        assert filepath.exists()

    def test_works_with_existing_directory(self, tmp_output_dir, sample_df):
        """Should work fine if directory already exists."""
        tmp_output_dir.mkdir(parents=True, exist_ok=True)
        storage = CSVStorage(output_dir=tmp_output_dir)

        filepath = storage.save(sample_df, "test", date(2026, 1, 1))
        assert filepath.exists()


class TestStorageErrors:
    """Tests for error handling in storage."""

    def test_empty_dataframe_saves_headers_only(self, storage):
        """Empty DataFrame should save with headers only."""
        empty_df = pd.DataFrame(columns=["symbol", "ltp"])
        filepath = storage.save(empty_df, "empty", date(2026, 1, 1))

        df_read = pd.read_csv(filepath)
        assert len(df_read) == 0
        assert list(df_read.columns) == ["symbol", "ltp"]
