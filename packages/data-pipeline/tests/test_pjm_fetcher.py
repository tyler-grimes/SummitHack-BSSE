"""Tests for PjmFetcher — pagination, fetch methods, dict conversion."""

from datetime import date, datetime
from unittest.mock import AsyncMock, patch

import httpx
from src.fetchers.pjm import PjmFetcher, _ancillary_to_dict, _da_to_dict, _rt_to_dict, _utc_str
from src.models import PjmAncillaryRecord, PjmDaLmpRecord, PjmRtLmpRecord

# ── Helpers ───────────────────────────────────────────────────────────────────

def _make_fetcher() -> PjmFetcher:
    fetcher = PjmFetcher()
    fetcher._client = AsyncMock(spec=httpx.AsyncClient)
    return fetcher


def _rt_raw(**overrides) -> dict:
    base = {
        "datetime_beginning_utc": "2024-01-15T00:00:00+00:00",
        "pnode_id": 12345,
        "pnode_name": "AEP GEN HUB",
        "total_lmp_rt": 38.50,
        "system_energy_price_rt": 36.00,
        "congestion_price_rt": 2.00,
        "marginal_loss_price_rt": 0.50,
    }
    base.update(overrides)
    return base


def _da_raw(**overrides) -> dict:
    base = {
        "datetime_beginning_utc": "2024-01-15T00:00:00+00:00",
        "pnode_id": 99,
        "pnode_name": "DOM HUB",
        "total_lmp_da": 45.0,
        "system_energy_price_da": 43.0,
        "congestion_price_da": 1.5,
        "marginal_loss_price_da": 0.5,
    }
    base.update(overrides)
    return base


def _ancillary_raw(**overrides) -> dict:
    base = {
        "datetime_beginning_utc": "2024-01-15T00:00:00+00:00",
        "ancillary_service": "REG",
        "unit": "MW",
        "value": 12.5,
    }
    base.update(overrides)
    return base


# ── _utc_str ──────────────────────────────────────────────────────────────────

class TestUtcStr:
    def test_produces_iso_format_with_timezone(self):
        result = _utc_str(date(2024, 1, 15))
        assert "2024-01-15" in result
        assert result.endswith("+00:00") or result.endswith("Z") or "00:00" in result, (
            "_utc_str should produce a UTC-offset ISO string"
        )

    def test_time_component_is_midnight(self):
        result = _utc_str(date(2024, 6, 1))
        # datetime(2024, 6, 1, tzinfo=utc).isoformat() → "2024-06-01T00:00:00+00:00"
        assert "T00:00:00" in result, "_utc_str should produce midnight UTC"


# ── _get_paginated (single page) ──────────────────────────────────────────────

class TestGetPaginated:
    async def test_single_page_list_response(self):
        """PJM sometimes returns a plain list; _get_paginated must handle it."""
        fetcher = _make_fetcher()
        records = [_rt_raw()]

        with patch.object(fetcher, "_get", AsyncMock(return_value=records)):
            result = await fetcher._get_paginated("rt_hrl_lmps", {})

        assert result == records, "Single page list response should return all records"

    async def test_single_page_dict_with_items_key(self):
        """Response may be a dict with an 'items' key."""
        fetcher = _make_fetcher()
        records = [_rt_raw()]

        with patch.object(fetcher, "_get", AsyncMock(return_value={"items": records})):
            result = await fetcher._get_paginated("rt_hrl_lmps", {})

        assert result == records

    async def test_empty_response_returns_empty_list(self):
        fetcher = _make_fetcher()

        with patch.object(fetcher, "_get", AsyncMock(return_value=[])):
            result = await fetcher._get_paginated("rt_hrl_lmps", {})

        assert result == [], "Empty response should return empty list"

    async def test_pagination_continues_when_full_page(self):
        """When batch size equals page_size, next page is fetched."""
        import src.config as cfg_module
        fetcher = _make_fetcher()

        # Create two pages; first full (page_size records), second partial
        page_size = 2
        page1 = [_rt_raw(pnode_name="NODE_A"), _rt_raw(pnode_name="NODE_B")]
        page2 = [_rt_raw(pnode_name="NODE_C")]

        get_mock = AsyncMock(side_effect=[page1, page2])
        with patch.object(fetcher, "_get", get_mock), \
             patch.object(cfg_module.Config, "pjm_page_size", page_size):
            result = await fetcher._get_paginated("rt_hrl_lmps", {})

        assert len(result) == 3, "Both pages should be aggregated"
        assert get_mock.call_count == 2, "Should fetch exactly 2 pages"

    async def test_pagination_stops_when_partial_page(self):
        """When batch < page_size, no more pages exist — stop immediately."""
        fetcher = _make_fetcher()

        partial_page = [_rt_raw()]  # 1 record < default page_size of 50_000
        get_mock = AsyncMock(return_value=partial_page)
        with patch.object(fetcher, "_get", get_mock):
            result = await fetcher._get_paginated("rt_hrl_lmps", {})

        assert get_mock.call_count == 1, "Should stop after first partial page"
        assert len(result) == 1

    async def test_start_row_incremented_correctly(self):
        """startRow for page 2 must equal 1 + len(page1)."""
        import src.config as cfg_module
        fetcher = _make_fetcher()
        page_size = 2
        page1 = [_rt_raw(pnode_name="A"), _rt_raw(pnode_name="B")]
        page2 = [_rt_raw(pnode_name="C")]

        get_mock = AsyncMock(side_effect=[page1, page2])
        with patch.object(fetcher, "_get", get_mock), \
             patch.object(cfg_module.Config, "pjm_page_size", page_size):
            await fetcher._get_paginated("endpoint", {"extra": "param"})

        # Second call should have startRow = 1 + 2 = 3
        second_call_params = get_mock.call_args_list[1][1]["params"]
        assert second_call_params["startRow"] == 3, (
            "Second page startRow should be 1 + len(page1) = 3"
        )


# ── fetch_rt_lmp ──────────────────────────────────────────────────────────────

class TestPjmFetchRtLmp:
    async def test_happy_path_single_node(self):
        fetcher = _make_fetcher()
        raw = [_rt_raw()]

        with patch.object(fetcher, "_get_paginated", AsyncMock(return_value=raw)):
            results = await fetcher.fetch_rt_lmp(
                ["AEP GEN HUB"], date(2024, 1, 15), date(2024, 1, 15)
            )

        assert len(results) == 1
        assert results[0]["iso"] == "PJM"
        assert results[0]["node"] == "AEP GEN HUB"
        assert "timestamp" in results[0]

    async def test_lmp_components_mapped_correctly(self):
        fetcher = _make_fetcher()
        raw = [_rt_raw(total_lmp_rt=50.0, system_energy_price_rt=46.0,
                        congestion_price_rt=3.0, marginal_loss_price_rt=1.0)]

        with patch.object(fetcher, "_get_paginated", AsyncMock(return_value=raw)):
            results = await fetcher.fetch_rt_lmp(["AEP GEN HUB"], date(2024, 1, 15), date(2024, 1, 15))

        r = results[0]
        assert r["lmp"] == 50.0
        assert r["energy"] == 46.0
        assert r["congestion"] == 3.0
        assert r["loss"] == 1.0

    async def test_empty_node_list_still_fetches(self):
        """Empty nodes list sends empty pnode_name param, not raising an error."""
        fetcher = _make_fetcher()

        with patch.object(fetcher, "_get_paginated", AsyncMock(return_value=[])) as mock_pg:
            results = await fetcher.fetch_rt_lmp([], date(2024, 1, 15), date(2024, 1, 15))

        assert results == [], "Empty nodes → empty results"
        mock_pg.assert_called_once()

    async def test_empty_node_list_sends_empty_string_param(self):
        """When nodes=[], pnode_name should be '' (not crash)."""
        fetcher = _make_fetcher()
        get_pg_mock = AsyncMock(return_value=[])

        with patch.object(fetcher, "_get_paginated", get_pg_mock):
            await fetcher.fetch_rt_lmp([], date(2024, 1, 15), date(2024, 1, 15))

        call_params = get_pg_mock.call_args[0][1]  # second positional arg is params dict
        assert call_params["pnode_name"] == "", (
            "Empty node list should send pnode_name='' not raise an error"
        )

    async def test_zero_price_included(self):
        fetcher = _make_fetcher()
        raw = [_rt_raw(total_lmp_rt=0.0, system_energy_price_rt=0.0,
                        congestion_price_rt=0.0, marginal_loss_price_rt=0.0)]

        with patch.object(fetcher, "_get_paginated", AsyncMock(return_value=raw)):
            results = await fetcher.fetch_rt_lmp(["AEP GEN HUB"], date(2024, 1, 15), date(2024, 1, 15))

        assert results[0]["lmp"] == 0.0

    async def test_negative_price_included(self):
        fetcher = _make_fetcher()
        raw = [_rt_raw(total_lmp_rt=-30.0, system_energy_price_rt=-30.0,
                        congestion_price_rt=0.0, marginal_loss_price_rt=0.0)]

        with patch.object(fetcher, "_get_paginated", AsyncMock(return_value=raw)):
            results = await fetcher.fetch_rt_lmp(["AEP GEN HUB"], date(2024, 1, 15), date(2024, 1, 15))

        assert results[0]["lmp"] == -30.0

    async def test_nodes_joined_with_semicolon(self):
        fetcher = _make_fetcher()
        get_pg_mock = AsyncMock(return_value=[])

        with patch.object(fetcher, "_get_paginated", get_pg_mock):
            await fetcher.fetch_rt_lmp(
                ["AEP GEN HUB", "DOM HUB"], date(2024, 1, 15), date(2024, 1, 15)
            )

        params = get_pg_mock.call_args[0][1]
        assert params["pnode_name"] == "AEP GEN HUB;DOM HUB", (
            "Multiple nodes must be semicolon-joined in pnode_name param"
        )


# ── fetch_da_lmp ──────────────────────────────────────────────────────────────

class TestPjmFetchDaLmp:
    async def test_happy_path(self):
        fetcher = _make_fetcher()
        raw = [_da_raw()]

        with patch.object(fetcher, "_get_paginated", AsyncMock(return_value=raw)):
            results = await fetcher.fetch_da_lmp(["DOM HUB"], date(2024, 1, 15), date(2024, 1, 15))

        assert len(results) == 1
        assert results[0]["iso"] == "PJM"
        assert results[0]["node"] == "DOM HUB"

    async def test_da_lmp_components_correct(self):
        fetcher = _make_fetcher()
        raw = [_da_raw(total_lmp_da=60.0, system_energy_price_da=57.0,
                        congestion_price_da=2.0, marginal_loss_price_da=1.0)]

        with patch.object(fetcher, "_get_paginated", AsyncMock(return_value=raw)):
            results = await fetcher.fetch_da_lmp(["DOM HUB"], date(2024, 1, 15), date(2024, 1, 15))

        r = results[0]
        assert r["lmp"] == 60.0
        assert r["energy"] == 57.0
        assert r["congestion"] == 2.0
        assert r["loss"] == 1.0

    async def test_empty_response(self):
        fetcher = _make_fetcher()

        with patch.object(fetcher, "_get_paginated", AsyncMock(return_value=[])):
            results = await fetcher.fetch_da_lmp(["DOM HUB"], date(2024, 1, 15), date(2024, 1, 15))

        assert results == []


# ── fetch_ancillary_prices ────────────────────────────────────────────────────

class TestPjmFetchAncillaryPrices:
    async def test_filters_by_service_type(self):
        fetcher = _make_fetcher()
        raw = [
            _ancillary_raw(ancillary_service="REG", value=10.0),
            _ancillary_raw(ancillary_service="SYNC", value=5.0),
            _ancillary_raw(ancillary_service="UNKNOWN", value=999.0),
        ]

        with patch.object(fetcher, "_get_paginated", AsyncMock(return_value=raw)):
            results = await fetcher.fetch_ancillary_prices(
                ["REG", "SYNC"], date(2024, 1, 15), date(2024, 1, 15)
            )

        assert len(results) == 2, "UNKNOWN service must be filtered out"
        services = {r["service"] for r in results}
        assert "UNKNOWN" not in services

    async def test_empty_raw_returns_empty_list(self):
        fetcher = _make_fetcher()

        with patch.object(fetcher, "_get_paginated", AsyncMock(return_value=[])):
            results = await fetcher.fetch_ancillary_prices(
                ["REG"], date(2024, 1, 15), date(2024, 1, 15)
            )

        assert results == []

    async def test_mileage_is_none_for_pjm(self):
        """PJM ancillary records do not carry mileage — always None."""
        fetcher = _make_fetcher()
        raw = [_ancillary_raw(ancillary_service="REG")]

        with patch.object(fetcher, "_get_paginated", AsyncMock(return_value=raw)):
            results = await fetcher.fetch_ancillary_prices(["REG"], date(2024, 1, 15), date(2024, 1, 15))

        assert results[0]["mileage"] is None, "PJM ancillary mileage must be None"

    async def test_ancillary_value_mapped_to_clearing_price(self):
        fetcher = _make_fetcher()
        raw = [_ancillary_raw(ancillary_service="REG", value=99.9)]

        with patch.object(fetcher, "_get_paginated", AsyncMock(return_value=raw)):
            results = await fetcher.fetch_ancillary_prices(["REG"], date(2024, 1, 15), date(2024, 1, 15))

        assert results[0]["clearing_price"] == 99.9, "value field should map to clearing_price"


# ── Dict converter helpers ────────────────────────────────────────────────────

class TestRtToDict:
    def _make_rt_record(self, **overrides) -> PjmRtLmpRecord:
        base = _rt_raw()
        base.update(overrides)
        return PjmRtLmpRecord.model_validate(base)

    def test_all_required_keys_present(self):
        r = _rt_to_dict(self._make_rt_record())
        assert set(r.keys()) == {"timestamp", "iso", "node", "lmp", "energy", "congestion", "loss"}

    def test_iso_is_pjm(self):
        assert _rt_to_dict(self._make_rt_record())["iso"] == "PJM"

    def test_timestamp_is_isoformat_string(self):
        result = _rt_to_dict(self._make_rt_record())
        # Should be parseable back to datetime
        dt = datetime.fromisoformat(result["timestamp"])
        assert dt is not None


class TestDaToDict:
    def _make_da_record(self, **overrides) -> PjmDaLmpRecord:
        base = _da_raw()
        base.update(overrides)
        return PjmDaLmpRecord.model_validate(base)

    def test_all_required_keys_present(self):
        r = _da_to_dict(self._make_da_record())
        assert set(r.keys()) == {"timestamp", "iso", "node", "lmp", "energy", "congestion", "loss"}

    def test_iso_is_pjm(self):
        assert _da_to_dict(self._make_da_record())["iso"] == "PJM"


class TestAncillaryToDict:
    def test_all_keys_present(self):
        r_model = PjmAncillaryRecord.model_validate(_ancillary_raw())
        result = _ancillary_to_dict(r_model)
        assert set(result.keys()) == {"timestamp", "iso", "service", "clearing_price", "mileage"}

    def test_iso_is_pjm(self):
        r_model = PjmAncillaryRecord.model_validate(_ancillary_raw())
        assert _ancillary_to_dict(r_model)["iso"] == "PJM"
