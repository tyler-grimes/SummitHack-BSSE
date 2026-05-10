"""Tests for ErcotFetcher — token refresh, pagination, fetch methods."""

import time
from datetime import date
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
from src.fetchers.ercot import ErcotFetcher

# ── Token refresh logic ───────────────────────────────────────────────────────

class TestTokenRefresh:
    async def _make_fetcher_with_client(self) -> ErcotFetcher:
        """Return an ErcotFetcher that has a mock HTTP client attached."""
        fetcher = ErcotFetcher()
        fetcher._client = AsyncMock(spec=httpx.AsyncClient)
        return fetcher

    def _mock_token_response(self, expires_in: int = 3600) -> MagicMock:
        resp = MagicMock()
        resp.raise_for_status = MagicMock()
        resp.json.return_value = {"id_token": "tok-abc123", "expires_in": expires_in}
        return resp

    async def test_token_refreshed_when_not_set(self):
        """Token is None on init, so _auth_headers must trigger _refresh_token."""
        fetcher = await self._make_fetcher_with_client()
        fetcher._client.post = AsyncMock(return_value=self._mock_token_response())

        headers = await fetcher._auth_headers()

        fetcher._client.post.assert_called_once(), "Token should be fetched on first use"
        assert headers["Authorization"] == "Bearer tok-abc123"

    async def test_token_refreshed_when_expired(self):
        """Token is set but expiry time is in the past — must refresh."""
        fetcher = await self._make_fetcher_with_client()
        fetcher._token = "old-token"
        fetcher._token_expires_at = time.time() - 10  # already expired
        fetcher._client.post = AsyncMock(return_value=self._mock_token_response())

        await fetcher._auth_headers()

        fetcher._client.post.assert_called_once(), (
            "Token should be refreshed when expired"
        )

    async def test_token_refreshed_within_60s_buffer(self):
        """Token expires in 30 seconds — within the 60s buffer, must refresh."""
        fetcher = await self._make_fetcher_with_client()
        fetcher._token = "near-expired"
        fetcher._token_expires_at = time.time() + 30  # expires in 30s (< 60s buffer)
        fetcher._client.post = AsyncMock(return_value=self._mock_token_response())

        await fetcher._auth_headers()

        fetcher._client.post.assert_called_once(), (
            "Token should be refreshed when within 60s of expiry"
        )

    async def test_token_not_refreshed_when_valid(self):
        """Token has 120 seconds left — no refresh needed."""
        fetcher = await self._make_fetcher_with_client()
        fetcher._token = "valid-token"
        fetcher._token_expires_at = time.time() + 120  # expires in 2 minutes
        fetcher._client.post = AsyncMock(return_value=self._mock_token_response())

        headers = await fetcher._auth_headers()

        fetcher._client.post.assert_not_called(), (
            "Token should NOT be refreshed when it still has > 60s left"
        )
        assert headers["Authorization"] == "Bearer valid-token"

    async def test_refresh_token_stores_id_token(self):
        """_refresh_token must store the id_token field, not access_token."""
        fetcher = await self._make_fetcher_with_client()
        fetcher._client.post = AsyncMock(return_value=self._mock_token_response(expires_in=1800))

        await fetcher._refresh_token()

        assert fetcher._token == "tok-abc123", (
            "Should store id_token, not access_token or other field"
        )

    async def test_refresh_token_sets_expiry(self):
        """_token_expires_at must be set to approximately now + expires_in."""
        fetcher = await self._make_fetcher_with_client()
        fetcher._client.post = AsyncMock(return_value=self._mock_token_response(expires_in=3600))

        before = time.time()
        await fetcher._refresh_token()
        after = time.time()

        assert before + 3600 <= fetcher._token_expires_at <= after + 3600, (
            "Token expiry should be set to now + expires_in"
        )

    async def test_subscription_key_in_headers(self):
        """Auth headers must include Ocp-Apim-Subscription-Key."""
        fetcher = await self._make_fetcher_with_client()
        fetcher._token = "tok"
        fetcher._token_expires_at = time.time() + 3600

        with patch("src.fetchers.ercot.config") as mock_cfg:
            mock_cfg.ercot_subscription_key = "my-sub-key"
            headers = await fetcher._auth_headers()

        assert headers["Ocp-Apim-Subscription-Key"] == "my-sub-key"


# ── Pagination ────────────────────────────────────────────────────────────────

class TestGetAllPages:
    def _make_page_response(self, records: list, current_page: int, total_pages: int) -> dict:
        return {
            "data": records,
            "_meta": {
                "totalRecords": len(records),
                "pageSize": 2,
                "totalPages": total_pages,
                "currentPage": current_page,
            },
        }

    async def test_single_page_returns_all_records(self):
        fetcher = ErcotFetcher()
        fetcher._token = "tok"
        fetcher._token_expires_at = time.time() + 3600
        fetcher._client = AsyncMock(spec=httpx.AsyncClient)

        page1 = self._make_page_response([{"a": 1}, {"a": 2}], current_page=1, total_pages=1)

        with patch.object(fetcher, "_get", AsyncMock(return_value=page1)):
            records = await fetcher._get_all_pages("some/path", {"param": "val"})

        assert records == [{"a": 1}, {"a": 2}], "Single page should return all records"

    async def test_multiple_pages_aggregated(self):
        fetcher = ErcotFetcher()
        fetcher._token = "tok"
        fetcher._token_expires_at = time.time() + 3600
        fetcher._client = AsyncMock(spec=httpx.AsyncClient)

        page1 = self._make_page_response([{"a": 1}, {"a": 2}], current_page=1, total_pages=2)
        page2 = self._make_page_response([{"a": 3}], current_page=2, total_pages=2)

        with patch.object(fetcher, "_get", AsyncMock(side_effect=[page1, page2])):
            records = await fetcher._get_all_pages("some/path", {"param": "val"})

        assert len(records) == 3, "Two pages should be aggregated into 3 records"
        assert records == [{"a": 1}, {"a": 2}, {"a": 3}]

    async def test_empty_response_returns_empty_list(self):
        fetcher = ErcotFetcher()
        fetcher._token = "tok"
        fetcher._token_expires_at = time.time() + 3600
        fetcher._client = AsyncMock(spec=httpx.AsyncClient)

        empty_page = self._make_page_response([], current_page=1, total_pages=0)

        with patch.object(fetcher, "_get", AsyncMock(return_value=empty_page)):
            records = await fetcher._get_all_pages("some/path", {})

        assert records == [], "Empty data response should return empty list"

    async def test_page_number_incremented_per_request(self):
        fetcher = ErcotFetcher()
        fetcher._token = "tok"
        fetcher._token_expires_at = time.time() + 3600
        fetcher._client = AsyncMock(spec=httpx.AsyncClient)

        page1 = self._make_page_response([{"x": 1}], current_page=1, total_pages=2)
        page2 = self._make_page_response([{"x": 2}], current_page=2, total_pages=2)

        get_mock = AsyncMock(side_effect=[page1, page2])
        with patch.object(fetcher, "_get", get_mock):
            await fetcher._get_all_pages("path", {"q": "v"})

        calls = get_mock.call_args_list
        assert calls[0][1]["params"]["page"] == 1 or calls[0][0][1].get("page") == 1 or \
               calls[0][1].get("params", {}).get("page") == 1, "First call should use page=1"


# ── fetch_rt_lmp / fetch_da_lmp ───────────────────────────────────────────────

class TestFetchRtLmp:
    async def _raw_spp_record(self, node: str = "HB_NORTH", price: float = 30.0) -> dict:
        return {
            "deliveryDate": "2024-01-15",
            "deliveryHour": 3,
            "deliveryInterval": 2,
            "settlementPoint": node,
            "settlementPointType": "HU",
            "settlementPointPrice": price,
        }

    async def test_happy_path_returns_dicts(self):
        fetcher = ErcotFetcher()
        fetcher._token = "tok"
        fetcher._token_expires_at = time.time() + 3600
        fetcher._client = AsyncMock(spec=httpx.AsyncClient)

        raw = [await self._raw_spp_record()]
        with patch.object(fetcher, "_get_all_pages", AsyncMock(return_value=raw)):
            results = await fetcher.fetch_rt_lmp(
                ["HB_NORTH"], date(2024, 1, 15), date(2024, 1, 15)
            )

        assert len(results) == 1
        assert results[0]["iso"] == "ERCOT"
        assert results[0]["node"] == "HB_NORTH"
        assert "timestamp" in results[0]

    async def test_empty_node_list_returns_empty(self):
        fetcher = ErcotFetcher()
        fetcher._token = "tok"
        fetcher._token_expires_at = time.time() + 3600
        fetcher._client = AsyncMock(spec=httpx.AsyncClient)

        with patch.object(fetcher, "_get_all_pages", AsyncMock(return_value=[])):
            results = await fetcher.fetch_rt_lmp([], date(2024, 1, 15), date(2024, 1, 15))

        assert results == [], "Empty node list should return empty results"

    async def test_multiple_nodes_combined(self):
        fetcher = ErcotFetcher()
        fetcher._token = "tok"
        fetcher._token_expires_at = time.time() + 3600
        fetcher._client = AsyncMock(spec=httpx.AsyncClient)

        north_record = await self._raw_spp_record("HB_NORTH", 30.0)
        south_record = await self._raw_spp_record("HB_SOUTH", 35.0)

        get_pages = AsyncMock(side_effect=[[north_record], [south_record]])
        with patch.object(fetcher, "_get_all_pages", get_pages):
            results = await fetcher.fetch_rt_lmp(
                ["HB_NORTH", "HB_SOUTH"], date(2024, 1, 15), date(2024, 1, 15)
            )

        assert len(results) == 2, "Records from both nodes should be combined"
        nodes = {r["node"] for r in results}
        assert "HB_NORTH" in nodes
        assert "HB_SOUTH" in nodes


class TestFetchDaLmp:
    async def _raw_dam_record(self, node: str = "HB_NORTH", price: float = 40.0) -> dict:
        return {
            "deliveryDate": "2024-01-15",
            "deliveryHour": 12,
            "settlementPoint": node,
            "settlementPointType": "HU",
            "settlementPointPrice": price,
        }

    async def test_happy_path_returns_dicts(self):
        fetcher = ErcotFetcher()
        fetcher._token = "tok"
        fetcher._token_expires_at = time.time() + 3600
        fetcher._client = AsyncMock(spec=httpx.AsyncClient)

        raw = [await self._raw_dam_record()]
        with patch.object(fetcher, "_get_all_pages", AsyncMock(return_value=raw)):
            results = await fetcher.fetch_da_lmp(
                ["HB_NORTH"], date(2024, 1, 15), date(2024, 1, 15)
            )

        assert len(results) == 1
        assert results[0]["iso"] == "ERCOT"
        assert "timestamp" in results[0]

    async def test_empty_response_returns_empty_list(self):
        fetcher = ErcotFetcher()
        fetcher._token = "tok"
        fetcher._token_expires_at = time.time() + 3600
        fetcher._client = AsyncMock(spec=httpx.AsyncClient)

        with patch.object(fetcher, "_get_all_pages", AsyncMock(return_value=[])):
            results = await fetcher.fetch_da_lmp(
                ["HB_NORTH"], date(2024, 1, 15), date(2024, 1, 15)
            )

        assert results == []


# ── fetch_ancillary_prices ────────────────────────────────────────────────────

class TestFetchAncillaryPrices:
    async def test_filters_by_service_type(self):
        fetcher = ErcotFetcher()
        fetcher._token = "tok"
        fetcher._token_expires_at = time.time() + 3600
        fetcher._client = AsyncMock(spec=httpx.AsyncClient)

        raw = [
            {"deliveryDate": "2024-01-15", "ancillaryType": "Reg-Up", "mcpc": 5.0},
            {"deliveryDate": "2024-01-15", "ancillaryType": "Reg-Down", "mcpc": 3.0},
            {"deliveryDate": "2024-01-15", "ancillaryType": "UNKNOWN_SERVICE", "mcpc": 99.0},
        ]
        with patch.object(fetcher, "_get_all_pages", AsyncMock(return_value=raw)):
            results = await fetcher.fetch_ancillary_prices(
                ["Reg-Up", "Reg-Down"], date(2024, 1, 15), date(2024, 1, 15)
            )

        assert len(results) == 2, "UNKNOWN_SERVICE should be filtered out"
        service_names = {r["service"] for r in results}
        assert "UNKNOWN_SERVICE" not in service_names

    async def test_empty_raw_returns_empty_list(self):
        fetcher = ErcotFetcher()
        fetcher._token = "tok"
        fetcher._token_expires_at = time.time() + 3600
        fetcher._client = AsyncMock(spec=httpx.AsyncClient)

        with patch.object(fetcher, "_get_all_pages", AsyncMock(return_value=[])):
            results = await fetcher.fetch_ancillary_prices(
                ["Reg-Up"], date(2024, 1, 15), date(2024, 1, 15)
            )

        assert results == []

    async def test_mileage_is_none(self):
        fetcher = ErcotFetcher()
        fetcher._token = "tok"
        fetcher._token_expires_at = time.time() + 3600
        fetcher._client = AsyncMock(spec=httpx.AsyncClient)

        raw = [{"deliveryDate": "2024-01-15", "ancillaryType": "RRS", "mcpc": 7.5}]
        with patch.object(fetcher, "_get_all_pages", AsyncMock(return_value=raw)):
            results = await fetcher.fetch_ancillary_prices(
                ["RRS"], date(2024, 1, 15), date(2024, 1, 15)
            )

        assert results[0]["mileage"] is None, "ERCOT does not provide mileage data"
