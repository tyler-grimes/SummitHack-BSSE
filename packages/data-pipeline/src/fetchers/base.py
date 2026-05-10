import logging
from abc import ABC, abstractmethod
from datetime import date
from typing import Any

import httpx
from tenacity import retry, retry_if_exception, stop_after_attempt, wait_exponential

logger = logging.getLogger(__name__)

_RETRYABLE_STATUS_CODES = frozenset({429, 500, 502, 503, 504})


def _is_retryable(exc: BaseException) -> bool:
    if isinstance(exc, httpx.HTTPStatusError):
        return exc.response.status_code in _RETRYABLE_STATUS_CODES
    return True  # retry on network errors (ConnectError, TimeoutException, etc.)


class BaseFetcher(ABC):
    """Base class for ISO data fetchers. Handles retries and HTTP client lifecycle."""

    def __init__(self, timeout: int = 30) -> None:
        self._client: httpx.AsyncClient | None = None
        self._timeout = timeout

    async def __aenter__(self) -> "BaseFetcher":
        self._client = httpx.AsyncClient(timeout=self._timeout)
        return self

    async def __aexit__(self, *_: object) -> None:
        if self._client:
            await self._client.aclose()

    @property
    def client(self) -> httpx.AsyncClient:
        if self._client is None:
            raise RuntimeError("Use as async context manager: async with Fetcher() as f:")
        return self._client

    @retry(
        retry=retry_if_exception(_is_retryable),
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=30),
        reraise=True,
    )
    async def _get(
        self,
        url: str,
        params: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        response = await self.client.get(url, params=params, headers=headers)
        response.raise_for_status()
        result: dict[str, Any] = response.json()
        return result

    @abstractmethod
    async def fetch_rt_lmp(
        self, nodes: list[str], start: date, end: date
    ) -> list[dict[str, Any]]:
        """Fetch real-time LMP records for given nodes and date range."""

    @abstractmethod
    async def fetch_da_lmp(
        self, nodes: list[str], start: date, end: date
    ) -> list[dict[str, Any]]:
        """Fetch day-ahead LMP records for given nodes and date range."""

    @abstractmethod
    async def fetch_ancillary_prices(
        self, services: list[str], start: date, end: date
    ) -> list[dict[str, Any]]:
        """Fetch ancillary service clearing prices."""
