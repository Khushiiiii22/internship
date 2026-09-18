"""
Data validation for NSE market data responses.

Validates JSON structure, expected columns, non-empty data,
and handles duplicate removal before data is persisted.
"""

import logging
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

import pandas as pd

from nse_downloader.config import DatasetConfig

logger = logging.getLogger(__name__)


class ValidationError(Exception):
    """Raised when data validation fails."""


@dataclass
class ValidationReport:
    """Summary of validation results for a dataset."""

    dataset_key: str
    raw_record_count: int
    valid_record_count: int
    duplicates_removed: int
    missing_columns: List[str]
    warnings: List[str]

    @property
    def is_valid(self) -> bool:
        return self.valid_record_count > 0 and len(self.missing_columns) == 0


class DataValidator:
    """Validates and cleans NSE market data before storage."""

    def validate(
        self,
        raw_data: Dict[str, Any],
        dataset: DatasetConfig,
    ) -> Tuple[pd.DataFrame, ValidationReport]:
        """Validate raw API response and return a cleaned DataFrame.

        Args:
            raw_data: Raw JSON response from NSE API.
            dataset: Dataset configuration with expected columns.

        Returns:
            Tuple of (cleaned DataFrame, validation report).

        Raises:
            ValidationError: If the data is invalid or unusable.
        """
        warnings: List[str] = []

        # ------------------------------------------------------------------
        # 1. Extract data array from response
        # ------------------------------------------------------------------
        data_list = self._extract_data(raw_data, dataset)

        # ------------------------------------------------------------------
        # 2. Convert to DataFrame
        # ------------------------------------------------------------------
        try:
            df = pd.DataFrame(data_list)
        except (ValueError, TypeError) as exc:
            raise ValidationError(
                f"Cannot convert {dataset.name} data to DataFrame: {exc}"
            ) from exc

        if df.empty:
            raise ValidationError(
                f"Empty DataFrame for {dataset.name} — no records found."
            )

        raw_count = len(df)
        logger.info(
            "Parsed %d raw records for %s", raw_count, dataset.name
        )

        # ------------------------------------------------------------------
        # 3. Check expected columns
        # ------------------------------------------------------------------
        actual_columns = set(df.columns)
        missing = [
            col for col in dataset.expected_columns
            if col not in actual_columns
        ]

        if missing:
            logger.warning(
                "Missing expected columns in %s: %s (available: %s)",
                dataset.name,
                missing,
                sorted(actual_columns),
            )
            # We raise if critical columns are missing, but allow partial
            # matches if at least 50% of expected columns are present
            match_ratio = 1 - len(missing) / len(dataset.expected_columns)
            if match_ratio < 0.5:
                raise ValidationError(
                    f"Too many missing columns in {dataset.name}: "
                    f"{missing}. Only {match_ratio:.0%} columns matched. "
                    f"Response structure may have changed."
                )
            warnings.append(
                f"Missing columns (non-critical): {missing}"
            )

        # ------------------------------------------------------------------
        # 4. Remove duplicates
        # ------------------------------------------------------------------
        dupes_before = len(df)
        if "symbol" in df.columns:
            df = df.drop_duplicates(subset=["symbol"], keep="first")
        else:
            df = df.drop_duplicates(keep="first")
        dupes_removed = dupes_before - len(df)

        if dupes_removed > 0:
            logger.info(
                "Removed %d duplicate records from %s",
                dupes_removed,
                dataset.name,
            )

        # ------------------------------------------------------------------
        # 5. Build report
        # ------------------------------------------------------------------
        report = ValidationReport(
            dataset_key=dataset.key,
            raw_record_count=raw_count,
            valid_record_count=len(df),
            duplicates_removed=dupes_removed,
            missing_columns=missing,
            warnings=warnings,
        )

        logger.info(
            "Validation complete for %s: %d valid records "
            "(removed %d duplicates)",
            dataset.name,
            report.valid_record_count,
            report.duplicates_removed,
        )

        return df, report

    def _extract_data(
        self,
        raw_data: Any,
        dataset: DatasetConfig,
    ) -> List[Dict[str, Any]]:
        """Extract the data array from the raw JSON response.

        Supports dot-separated paths in ``dataset.data_json_path``:

        * ``"data"``                    → ``resp["data"]``
        * ``"gainers.__first__.data"``  → ``resp["gainers"][<first_key>]["data"]``
        * ``"dataLtpGreater20"``        → also merges ``dataLtpLess20`` (52-week)

        The special token ``__first__`` means "use the first key of the current
        dict" — NSE often nests data under an index name like "NIFTY" or
        "All Securities" that we don't want to hard-code.
        """
        if not isinstance(raw_data, (dict, list)):
            raise ValidationError(
                f"Expected dict or list response for {dataset.name}, "
                f"got {type(raw_data).__name__}"
            )

        # If the top-level response is already a list of records, return it.
        if isinstance(raw_data, list):
            if len(raw_data) == 0:
                raise ValidationError(
                    f"Empty list response for {dataset.name}"
                )
            return raw_data

        if not raw_data:
            raise ValidationError(f"Empty response for {dataset.name}")

        # --- Special case: 52-week endpoint returns two arrays; merge them ---
        if "dataLtpGreater20" in raw_data and "dataLtpLess20" in raw_data:
            combined = (
                (raw_data.get("dataLtpGreater20") or [])
                + (raw_data.get("dataLtpLess20") or [])
            )
            if not combined:
                raise ValidationError(
                    f"Both 52-week data arrays are empty for {dataset.name}"
                )
            logger.info(
                "52-week: merged %d (>₹20) + %d (<₹20) = %d total records",
                len(raw_data.get("dataLtpGreater20") or []),
                len(raw_data.get("dataLtpLess20") or []),
                len(combined),
            )
            return combined

        # --- Walk the dot-separated data_json_path ---
        path_parts = dataset.data_json_path.split(".")
        current: Any = raw_data

        for part in path_parts:
            if part == "__first__":
                # Use the first key of the current dict (e.g. "NIFTY")
                if not isinstance(current, dict) or not current:
                    raise ValidationError(
                        f"Expected non-empty dict for __first__ token "
                        f"in {dataset.name}; got {type(current).__name__}"
                    )
                first_key = next(iter(current))
                logger.debug(
                    "data_json_path __first__ resolved to key '%s' for %s",
                    first_key, dataset.name,
                )
                current = current[first_key]

            elif isinstance(current, dict):
                if part in current:
                    current = current[part]
                else:
                    # Try common fallback keys before giving up
                    for fallback in ("data", "records", "items"):
                        if fallback in current:
                            logger.warning(
                                "Key '%s' not found in %s response; "
                                "falling back to '%s'",
                                part, dataset.name, fallback,
                            )
                            current = current[fallback]
                            break
                    else:
                        raise ValidationError(
                            f"Key '{part}' not found in {dataset.name} "
                            f"response. Available keys: {list(current.keys())}"
                        )
            else:
                raise ValidationError(
                    f"Cannot traverse path step '{part}' on "
                    f"{type(current).__name__} for {dataset.name}"
                )

        if not isinstance(current, list):
            raise ValidationError(
                f"Expected list at path '{dataset.data_json_path}' "
                f"for {dataset.name}, got {type(current).__name__}"
            )

        if len(current) == 0:
            raise ValidationError(
                f"Empty data array at '{dataset.data_json_path}' "
                f"for {dataset.name}"
            )

        return current
