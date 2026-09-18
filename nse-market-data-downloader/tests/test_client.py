"""
Tests for the NSE HTTP client.

Uses unittest.mock to simulate network responses without hitting NSE servers.
"""

import json
from unittest.mock import MagicMock, Mock, patch

import pytest
import requests

from nse_downloader.client import NSEClient, NSEClientError
from nse_downloader.config import DATASETS


@pytest.fixture
def client():
    """Create an NSEClient with fast settings for testing."""
    return NSEClient(
        timeout=5,
        max_retries=2,
        backoff_factor=0.01,  # near-instant retries in tests
        rate_limit_delay=0,   # no rate limiting in tests
    )


@pytest.fixture
def sample_dataset():
    """Return a sample dataset config for testing."""
    return DATASETS["top-gainers"]


class TestNSEClientSession:
    """Tests for session initialization and management."""

    @patch("nse_downloader.client.requests.Session")
    def test_session_initialized_on_first_fetch(
        self, mock_session_cls, client, sample_dataset
    ):
        """Session should be created and homepage hit on first fetch."""
        mock_session = MagicMock()
        mock_session_cls.return_value = mock_session

        # Homepage response
        mock_homepage = Mock()
        mock_homepage.raise_for_status = Mock()

        # API response
        mock_api = Mock()
        mock_api.status_code = 200
        mock_api.raise_for_status = Mock()
        mock_api.json.return_value = {"data": [{"symbol": "TCS"}]}
        mock_api.content = b'{"data": [{"symbol": "TCS"}]}'

        mock_session.get.side_effect = [mock_homepage, mock_api]
        mock_session.cookies.keys.return_value = ["nsit", "nseappid"]
        mock_session.headers = {}

        result = client.fetch(sample_dataset)

        # Verify homepage was hit first
        assert mock_session.get.call_count == 2
        assert result == {"data": [{"symbol": "TCS"}]}

    @patch("nse_downloader.client.requests.Session")
    def test_session_init_failure_raises(self, mock_session_cls, client, sample_dataset):
        """Should raise NSEClientError if fetch request fails."""
        mock_session = MagicMock()
        mock_session_cls.return_value = mock_session
        mock_session.get.side_effect = requests.ConnectionError("DNS failure")
        mock_session.headers = {}

        with pytest.raises(NSEClientError, match="Failed to fetch"):
            client.fetch(sample_dataset)


class TestNSEClientFetch:
    """Tests for data fetching."""

    @patch("nse_downloader.client.requests.Session")
    def test_successful_fetch(self, mock_session_cls, client, sample_dataset):
        """Should return parsed JSON on successful fetch."""
        mock_session = MagicMock()
        mock_session_cls.return_value = mock_session
        mock_session.headers = {}

        expected_data = {
            "data": [
                {"symbol": "TCS", "ltp": 3500, "perChange": 2.5},
                {"symbol": "INFY", "ltp": 1400, "perChange": 1.8},
            ]
        }

        mock_homepage = Mock()
        mock_homepage.raise_for_status = Mock()

        mock_api = Mock()
        mock_api.status_code = 200
        mock_api.raise_for_status = Mock()
        mock_api.json.return_value = expected_data
        mock_api.content = json.dumps(expected_data).encode()

        mock_session.get.side_effect = [mock_homepage, mock_api]
        mock_session.cookies.keys.return_value = ["nsit"]

        result = client.fetch(sample_dataset)
        assert result == expected_data

    @patch("nse_downloader.client.requests.Session")
    def test_timeout_triggers_retry(self, mock_session_cls, client, sample_dataset):
        """Should retry on timeout and succeed on subsequent attempt."""
        mock_session = MagicMock()
        mock_session_cls.return_value = mock_session
        mock_session.headers = {}

        mock_homepage = Mock()
        mock_homepage.raise_for_status = Mock()
        mock_session.cookies.keys.return_value = ["nsit"]

        # First call: timeout, second call: success
        mock_success = Mock()
        mock_success.status_code = 200
        mock_success.raise_for_status = Mock()
        mock_success.json.return_value = {"data": [{"symbol": "TCS"}]}
        mock_success.content = b'{"data": [{"symbol": "TCS"}]}'

        mock_session.get.side_effect = [
            mock_homepage,  # session init
            requests.exceptions.Timeout("timed out"),  # attempt 1
            mock_success,  # attempt 2
        ]

        result = client.fetch(sample_dataset)
        assert result == {"data": [{"symbol": "TCS"}]}

    @patch("nse_downloader.client.requests.Session")
    def test_all_retries_exhausted_raises(
        self, mock_session_cls, client, sample_dataset
    ):
        """Should raise NSEClientError after all retries are exhausted."""
        mock_session = MagicMock()
        mock_session_cls.return_value = mock_session
        mock_session.headers = {}

        mock_homepage = Mock()
        mock_homepage.raise_for_status = Mock()
        mock_session.cookies.keys.return_value = ["nsit"]

        # All attempts fail
        mock_session.get.side_effect = [
            mock_homepage,
            requests.exceptions.ConnectionError("fail 1"),
            requests.exceptions.ConnectionError("fail 2"),
        ]

        with pytest.raises(NSEClientError, match="Failed to fetch"):
            client.fetch(sample_dataset)

    @patch("nse_downloader.client.requests.Session")
    def test_invalid_json_raises(self, mock_session_cls, client, sample_dataset):
        """Should raise NSEClientError on invalid JSON response."""
        mock_session = MagicMock()
        mock_session_cls.return_value = mock_session
        mock_session.headers = {}

        mock_homepage = Mock()
        mock_homepage.raise_for_status = Mock()
        mock_session.cookies.keys.return_value = ["nsit"]

        mock_api = Mock()
        mock_api.status_code = 200
        mock_api.raise_for_status = Mock()
        mock_api.json.side_effect = ValueError("No JSON")
        mock_api.content = b"<html>Not JSON</html>"

        mock_session.get.side_effect = [mock_homepage, mock_api]

        with pytest.raises(NSEClientError, match="Invalid JSON"):
            client.fetch(sample_dataset)

    @patch("nse_downloader.client.requests.Session")
    def test_403_triggers_session_refresh(
        self, mock_session_cls, client, sample_dataset
    ):
        """Should refresh session on 403 and retry."""
        mock_session = MagicMock()
        mock_session_cls.return_value = mock_session
        mock_session.headers = {}
        mock_session.cookies.keys.return_value = ["nsit"]

        mock_homepage = Mock()
        mock_homepage.raise_for_status = Mock()

        # 403 response
        mock_403 = Mock()
        mock_403.status_code = 403

        # Success after refresh
        mock_success = Mock()
        mock_success.status_code = 200
        mock_success.raise_for_status = Mock()
        mock_success.json.return_value = {"data": [{"symbol": "TCS"}]}
        mock_success.content = b'{"data": [{"symbol": "TCS"}]}'

        mock_session.get.side_effect = [
            mock_homepage,   # init
            mock_403,        # attempt 1 → 403
            mock_homepage,   # refresh
            mock_success,    # attempt 2
        ]

        result = client.fetch(sample_dataset)
        assert result == {"data": [{"symbol": "TCS"}]}


class TestNSEClientContextManager:
    """Tests for context manager protocol."""

    def test_context_manager_closes_session(self):
        """Session should be closed when exiting context manager."""
        client = NSEClient(
            timeout=5, max_retries=1, backoff_factor=0, rate_limit_delay=0
        )
        with client:
            pass
        # After exiting, session should be None
        assert client._session is None
