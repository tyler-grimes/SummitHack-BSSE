"""Tests for BaseFetcher._get — retry behavior, rate limiting, error handling."""

import httpx
import pytest
import respx
from src.fetchers.ercot import ErcotFetcher

# ── Helpers ───────────────────────────────────────────────────────────────────

async def _fetcher_get(url: str, params: dict | None = None) -> dict:
    """Enter ErcotFetcher context and call _get directly (bypasses auth)."""
    async with ErcotFetcher() as f:
        return await f._get(url, params=params)


# ── Happy path ────────────────────────────────────────────────────────────────

class TestGetHappyPath:
    @respx.mock
    async def test_returns_json_on_200(self):
        respx.get("https://example.com/data").mock(
            return_value=httpx.Response(200, json={"items": [1, 2, 3]})
        )
        result = await _fetcher_get("https://example.com/data")
        assert result == {"items": [1, 2, 3]}, "Should return parsed JSON on 200"

    @respx.mock
    async def test_passes_query_params(self):
        route = respx.get("https://example.com/data").mock(
            return_value=httpx.Response(200, json={})
        )
        await _fetcher_get("https://example.com/data", params={"page": 1, "size": 50})
        assert route.called, "Route should have been called with params"


# ── 429 Rate limit triggers retry ─────────────────────────────────────────────

class TestRateLimitRetry:
    @respx.mock
    async def test_429_then_200_succeeds(self):
        """First call returns 429, second call returns 200 — should succeed after retry."""
        respx.get("https://example.com/data").mock(
            side_effect=[
                httpx.Response(429, text="Rate limited"),
                httpx.Response(200, json={"ok": True}),
            ]
        )
        result = await _fetcher_get("https://example.com/data")
        assert result == {"ok": True}, "Should succeed after retrying past 429"

    @respx.mock
    async def test_three_consecutive_429_raises(self):
        """All 3 attempts return 429 — tenacity reraises the last exception."""
        respx.get("https://example.com/data").mock(
            return_value=httpx.Response(429, text="Rate limited")
        )
        with pytest.raises(httpx.HTTPStatusError):
            await _fetcher_get("https://example.com/data")


# ── 500 triggers retry ────────────────────────────────────────────────────────

class TestServerErrorRetry:
    @respx.mock
    async def test_500_then_200_succeeds(self):
        """First call returns 500, second returns 200 — should retry and succeed."""
        respx.get("https://example.com/data").mock(
            side_effect=[
                httpx.Response(500, text="Internal Server Error"),
                httpx.Response(200, json={"data": []}),
            ]
        )
        result = await _fetcher_get("https://example.com/data")
        assert result == {"data": []}

    @respx.mock
    async def test_three_consecutive_500_raises(self):
        """All 3 attempts return 500 — raises after exhausting retries."""
        respx.get("https://example.com/data").mock(
            return_value=httpx.Response(500, text="Server error")
        )
        with pytest.raises(httpx.HTTPStatusError):
            await _fetcher_get("https://example.com/data")


# ── 400 non-retryable behavior ────────────────────────────────────────────────

class TestNonRetryable400:
    @respx.mock
    async def test_400_raises_immediately(self):
        """
        400 Bad Request should raise an error.

        NOTE: This tests the ACTUAL behavior. The implementation does NOT
        distinguish 400 from 500 in its retry logic — tenacity retries on
        ANY exception, so 400 will be retried up to 3 times before raising.
        This is a bug: non-retryable client errors are being retried.
        """
        call_count = 0

        def side_effect(request):
            nonlocal call_count
            call_count += 1
            return httpx.Response(400, text="Bad Request")

        respx.get("https://example.com/data").mock(side_effect=side_effect)

        with pytest.raises(httpx.HTTPStatusError):
            await _fetcher_get("https://example.com/data")

        assert call_count == 1, "400 must raise immediately — no retries for client errors"


# ── Context manager enforcement ───────────────────────────────────────────────

class TestContextManagerEnforcement:
    async def test_get_without_context_manager_raises(self):
        """Calling _get without entering the async context manager must raise RuntimeError."""
        fetcher = ErcotFetcher()
        with pytest.raises(RuntimeError, match="async context manager"):
            await fetcher._get("https://example.com")
