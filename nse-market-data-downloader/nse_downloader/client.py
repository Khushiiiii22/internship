"""
NSE HTTP client with session management, cookie handling, and retry logic.

Manages the complexities of accessing NSE's internal JSON API:
- Session cookies acquired by warming up with market-data pages (not homepage)
- Browser-like headers to pass NSE's anti-bot checks
- Exponential backoff retries on transient failures
- Automatic session refresh on 401/403
- Rate limiting between requests
"""

import logging
import time
from typing import Any, Dict, Optional

from curl_cffi import requests

from nse_downloader.config import (
    BACKOFF_FACTOR,
    DEFAULT_HEADERS,
    MAX_RETRIES,
    NSE_BASE_URL,
    RATE_LIMIT_DELAY,
    REQUEST_TIMEOUT,
    SESSION_WARM_UP_URLS,
    DatasetConfig,
)

logger = logging.getLogger(__name__)


class NSEClientError(Exception):
    """Raised when the NSE client encounters an unrecoverable error."""


class NSEClient:
    """HTTP client for fetching data from NSE India's internal JSON API.

    Handles session lifecycle, cookie management, and retries transparently.

    NSE uses Cloudflare and session-based protections. Hitting the homepage
    often returns 403. Instead we warm up via specific market-data pages
    which consistently return 200 and set the required cookies (nsit, nseappid).
    """

    def __init__(
        self,
        timeout: int = REQUEST_TIMEOUT,
        max_retries: int = MAX_RETRIES,
        backoff_factor: float = BACKOFF_FACTOR,
        rate_limit_delay: float = RATE_LIMIT_DELAY,
    ) -> None:
        self._timeout = timeout
        self._max_retries = max_retries
        self._backoff_factor = backoff_factor
        self._rate_limit_delay = rate_limit_delay
        self._session: Optional[requests.Session] = None
        self._last_request_time: float = 0.0

    # ------------------------------------------------------------------
    # Session lifecycle
    # ------------------------------------------------------------------

    def _create_session(self) -> requests.Session:
        """Create a new requests.Session with browser TLS impersonation."""
        session = requests.Session(impersonate="chrome")
        session.headers.update(DEFAULT_HEADERS)
        return session

    def _init_session(self) -> None:
        """Warm up the session by visiting NSE market-data pages.

        Visiting market-data pages (not the homepage, which Cloudflare
        often blocks) reliably sets the nsit/nseappid cookies that
        subsequent API calls require.
        """
        logger.info("Initializing NSE session (warming up cookies)...")
        self._session = self._create_session()

        for url in SESSION_WARM_UP_URLS:
            try:
                self._session.headers.update({"Referer": NSE_BASE_URL})
                resp = self._session.get(url, timeout=self._timeout)
                self._last_request_time = time.time()
                logger.info(
                    "Warm-up: GET %s → HTTP %d  cookies=%s",
                    url,
                    resp.status_code,
                    list(self._session.cookies.keys()),
                )
                time.sleep(0.8)   # brief pause between warm-up requests
            except requests.exceptions.RequestException as exc:
                logger.warning("Warm-up request failed for %s: %s", url, exc)

        if self._session.cookies:
            logger.info(
                "Session ready — cookies: %s",
                list(self._session.cookies.keys()),
            )
        else:
            logger.warning(
                "No cookies acquired during warm-up; API calls may fail."
            )

    def _refresh_session(self) -> None:
        """Force a full session refresh (called after 401/403)."""
        logger.info("Refreshing session...")
        self.close()
        self._init_session()

    def _ensure_session(self) -> None:
        """Lazily initialize the session on first use."""
        if self._session is None:
            self._init_session()

    def close(self) -> None:
        """Close the underlying HTTP session."""
        if self._session is not None:
            self._session.close()
            self._session = None
            logger.debug("Session closed.")

    # ------------------------------------------------------------------
    # Rate limiting
    # ------------------------------------------------------------------

    def _rate_limit(self) -> None:
        """Sleep if needed to honour the configured inter-request delay."""
        if self._rate_limit_delay <= 0:
            return
        elapsed = time.time() - self._last_request_time
        if elapsed < self._rate_limit_delay:
            sleep_time = self._rate_limit_delay - elapsed
            logger.debug("Rate limiting: sleeping %.2fs", sleep_time)
            time.sleep(sleep_time)

    # ------------------------------------------------------------------
    # Data fetching
    # ------------------------------------------------------------------

    def fetch(self, dataset: DatasetConfig) -> Dict[str, Any]:
        """Fetch JSON data for a dataset.

        Retries up to max_retries times with exponential backoff.
        On 401/403 the session is refreshed and the attempt is retried.

        Returns:
            Parsed JSON response as a dict.

        Raises:
            NSEClientError: After all retries are exhausted, or on
                unrecoverable errors (e.g. invalid JSON).
        """
        self._ensure_session()
        assert self._session is not None  # for type checker

        last_error: Optional[Exception] = None

        for attempt in range(1, self._max_retries + 1):
            self._rate_limit()
            
            # Rebuild headers for each attempt (in case session was refreshed)
            req_headers = dict(self._session.headers)
            req_headers.update({
                "Referer": dataset.referer,
                "Accept": "*/*",
                "Sec-Fetch-Dest": "empty",
                "Sec-Fetch-Mode": "cors",
                "Sec-Fetch-Site": "same-origin",
            })

            logger.info(
                "Fetching %s (attempt %d/%d): %s",
                dataset.name,
                attempt,
                self._max_retries,
                dataset.api_url,
            )

            try:
                response = self._session.get(
                    dataset.api_url,
                    headers=req_headers,
                    timeout=self._timeout,
                )
                self._last_request_time = time.time()

                # Handle auth failures — refresh session and retry
                if response.status_code in (401, 403):
                    logger.warning(
                        "HTTP %d for %s — refreshing session and retrying",
                        response.status_code,
                        dataset.name,
                    )
                    self._refresh_session()
                    assert self._session is not None
                    continue

                response.raise_for_status()

                # Parse JSON
                try:
                    data = response.json()
                except ValueError as exc:
                    last_error = exc
                    logger.warning(
                        "Invalid JSON for %s (likely Cloudflare HTML block). "
                        "Refreshing session and retrying...",
                        dataset.name
                    )
                    self._refresh_session()
                    assert self._session is not None
                    continue

                logger.info(
                    "Successfully fetched %s (%d bytes)",
                    dataset.name,
                    len(response.content),
                )
                return data

            except requests.exceptions.Timeout as exc:
                last_error = exc
                logger.warning(
                    "Timeout on %s attempt %d/%d: %s",
                    dataset.name,
                    attempt,
                    self._max_retries,
                    exc,
                )
            except requests.exceptions.ConnectionError as exc:
                last_error = exc
                logger.warning(
                    "Connection error on %s attempt %d/%d: %s",
                    dataset.name,
                    attempt,
                    self._max_retries,
                    exc,
                )
            except requests.exceptions.HTTPError as exc:
                last_error = exc
                logger.warning(
                    "HTTP error on %s attempt %d/%d: %s",
                    dataset.name,
                    attempt,
                    self._max_retries,
                    exc,
                )
            except NSEClientError:
                raise  # Don't retry JSON parse errors

            # Exponential backoff before next attempt
            if attempt < self._max_retries:
                wait = self._backoff_factor ** attempt
                logger.info("Waiting %.1fs before retry...", wait)
                time.sleep(wait)

        raise NSEClientError(
            f"Failed to fetch {dataset.name} after {self._max_retries} "
            f"attempts. Last error: {last_error}"
        )

    # ------------------------------------------------------------------
    # Context manager support
    # ------------------------------------------------------------------

    def __enter__(self) -> "NSEClient":
        return self

    def __exit__(self, *args: Any) -> None:
        self.close()
