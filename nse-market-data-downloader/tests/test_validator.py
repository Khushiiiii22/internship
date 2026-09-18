"""
Tests for the data validator.

Covers valid data, empty data, missing columns, duplicates,
and unexpected response formats.
"""

import pytest

from nse_downloader.config import DatasetConfig
from nse_downloader.validator import DataValidator, ValidationError


@pytest.fixture
def validator():
    return DataValidator()


@pytest.fixture
def sample_dataset():
    """Minimal dataset config for testing."""
    return DatasetConfig(
        key="test-dataset",
        name="Test Dataset",
        api_url="https://example.com/api/test",
        referer="https://example.com",
        csv_prefix="test",
        expected_columns=["symbol", "ltp", "perChange"],
    )


@pytest.fixture
def valid_response():
    """A valid API response with expected structure."""
    return {
        "data": [
            {"symbol": "TCS", "ltp": 3500.0, "perChange": 2.5, "extra": "x"},
            {"symbol": "INFY", "ltp": 1400.0, "perChange": 1.8, "extra": "y"},
            {"symbol": "WIPRO", "ltp": 450.0, "perChange": -0.5, "extra": "z"},
        ]
    }


class TestValidData:
    """Tests for valid data that should pass validation."""

    def test_valid_response_passes(self, validator, sample_dataset, valid_response):
        """Valid data should produce a DataFrame and a clean report."""
        df, report = validator.validate(valid_response, sample_dataset)

        assert len(df) == 3
        assert report.is_valid
        assert report.raw_record_count == 3
        assert report.valid_record_count == 3
        assert report.duplicates_removed == 0
        assert report.missing_columns == []

    def test_expected_columns_present(self, validator, sample_dataset, valid_response):
        """All expected columns should be present in the DataFrame."""
        df, _ = validator.validate(valid_response, sample_dataset)

        for col in sample_dataset.expected_columns:
            assert col in df.columns

    def test_extra_columns_preserved(self, validator, sample_dataset, valid_response):
        """Extra columns beyond expected ones should be preserved."""
        df, _ = validator.validate(valid_response, sample_dataset)
        assert "extra" in df.columns


class TestEmptyData:
    """Tests for empty or missing data."""

    def test_empty_dict_raises(self, validator, sample_dataset):
        """Empty dict should raise ValidationError."""
        with pytest.raises(ValidationError, match="Empty response"):
            validator.validate({}, sample_dataset)

    def test_empty_data_array_raises(self, validator, sample_dataset):
        """Empty data array should raise ValidationError."""
        with pytest.raises(ValidationError, match="Empty data array"):
            validator.validate({"data": []}, sample_dataset)

    def test_non_dict_response_raises(self, validator, sample_dataset):
        """Non-dict top-level response should raise ValidationError."""
        with pytest.raises(ValidationError, match="Expected dict"):
            validator.validate("not a dict", sample_dataset)

    def test_none_response_raises(self, validator, sample_dataset):
        """None response should raise ValidationError."""
        with pytest.raises(ValidationError, match="Expected dict"):
            validator.validate(None, sample_dataset)


class TestMissingColumns:
    """Tests for missing expected columns."""

    def test_some_missing_columns_warns(self, validator, sample_dataset):
        """Missing a minority of columns should produce warnings, not error."""
        response = {
            "data": [
                {"symbol": "TCS", "ltp": 3500.0},  # missing perChange
            ]
        }
        df, report = validator.validate(response, sample_dataset)

        assert len(df) == 1
        assert "perChange" in report.missing_columns
        assert len(report.warnings) > 0

    def test_all_columns_missing_raises(self, validator):
        """If too many expected columns are missing, raise ValidationError."""
        dataset = DatasetConfig(
            key="strict",
            name="Strict",
            api_url="https://example.com/api/test",
            referer="https://example.com",
            csv_prefix="strict",
            expected_columns=["col_a", "col_b", "col_c", "col_d"],
        )
        response = {
            "data": [
                {"other1": 1, "other2": 2},
            ]
        }

        with pytest.raises(ValidationError, match="Too many missing columns"):
            validator.validate(response, dataset)


class TestDuplicateHandling:
    """Tests for duplicate record removal."""

    def test_duplicates_removed_by_symbol(self, validator, sample_dataset):
        """Duplicate symbols should be removed (keep first)."""
        response = {
            "data": [
                {"symbol": "TCS", "ltp": 3500.0, "perChange": 2.5},
                {"symbol": "TCS", "ltp": 3510.0, "perChange": 2.8},
                {"symbol": "INFY", "ltp": 1400.0, "perChange": 1.8},
            ]
        }

        df, report = validator.validate(response, sample_dataset)

        assert len(df) == 2
        assert report.duplicates_removed == 1
        # First occurrence should be kept
        tcs_row = df[df["symbol"] == "TCS"].iloc[0]
        assert tcs_row["ltp"] == 3500.0

    def test_no_duplicates_no_removal(self, validator, sample_dataset, valid_response):
        """When there are no duplicates, count should be 0."""
        _, report = validator.validate(valid_response, sample_dataset)
        assert report.duplicates_removed == 0


class TestFallbackKeys:
    """Tests for fallback JSON path resolution."""

    def test_data_key_used_by_default(self, validator, sample_dataset):
        """Standard 'data' key should be used."""
        response = {
            "data": [{"symbol": "TCS", "ltp": 3500.0, "perChange": 2.5}]
        }
        df, _ = validator.validate(response, sample_dataset)
        assert len(df) == 1

    def test_fallback_to_alternate_keys(self, validator, sample_dataset):
        """Should fall back to known alternate keys like 'records'."""
        response = {
            "records": [{"symbol": "TCS", "ltp": 3500.0, "perChange": 2.5}]
        }
        # In this dataset config, data_json_path is "data". It should fallback to records.
        df, _ = validator.validate(response, sample_dataset)
        assert len(df) == 1

    def test_no_known_key_raises(self, validator, sample_dataset):
        """Should raise if no known key contains data."""
        response = {"unknownKey": "some value"}

        with pytest.raises(ValidationError, match="Key 'data' not found"):
            validator.validate(response, sample_dataset)

    def test_data_key_not_list_raises(self, validator, sample_dataset):
        """Should raise if 'data' key doesn't contain a list."""
        response = {"data": "not a list"}

        with pytest.raises(ValidationError, match="Expected list"):
            validator.validate(response, sample_dataset)


class TestValidationReport:
    """Tests for the ValidationReport dataclass."""

    def test_is_valid_when_records_and_no_missing(
        self, validator, sample_dataset, valid_response
    ):
        """Report should be valid when records exist and no columns missing."""
        _, report = validator.validate(valid_response, sample_dataset)
        assert report.is_valid is True

    def test_is_invalid_when_columns_missing(self, validator):
        """Report should be invalid when critical columns are missing."""
        dataset = DatasetConfig(
            key="test",
            name="Test",
            api_url="https://example.com/api/test",
            referer="https://example.com",
            csv_prefix="test",
            expected_columns=["symbol", "ltp", "perChange"],
        )
        response = {
            "data": [
                {"symbol": "TCS", "ltp": 3500.0},  # missing perChange
            ]
        }
        _, report = validator.validate(response, dataset)

        assert report.is_valid is False
        assert "perChange" in report.missing_columns
