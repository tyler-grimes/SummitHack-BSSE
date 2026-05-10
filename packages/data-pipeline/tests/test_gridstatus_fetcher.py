"""Adversarial tests for GridStatusFetcher — mocks asyncio.to_thread, no real API calls."""

from datetime import date
from unittest.mock import AsyncMock, patch

import numpy as np
import pandas as pd
import pytest
from src.fetchers.gridstatus import GridStatusFetcher

START = date(2024, 1, 15)
END = date(2024, 1, 15)


def _make_rt_df(nodes: list[str], prices: list[float] | None = None) -> pd.DataFrame:
    if prices is None:
        prices = [30.0] * len(nodes)
    return pd.DataFrame({
        "Interval Start": [pd.Timestamp("2024-01-15T01:00:00")] * len(nodes),
        "Settlement Point": nodes,
        "Settlement Point Price": prices,
    })


def _make_as_df() -> pd.DataFrame:
    return pd.DataFrame({
        "Interval Start": [pd.Timestamp("2024-01-15T00:00:00")],
        "Regulation Up": [5.0],
        "Regulation Down": [3.0],
        "Non-Spinning Reserves": [2.0],
        "Responsive Reserves": [4.0],
    })


# ── fetch_rt_lmp ──────────────────────────────────────────────────────────────

class TestFetchRtLmp:
    def _fetcher(self) -> GridStatusFetcher:
        with patch("src.fetchers.gridstatus.GridStatusClient"):
            return GridStatusFetcher("ERCOT")

    async def test_happy_path_returns_records(self):
        fetcher = self._fetcher()
        df = _make_rt_df(["HB_NORTH"])
        with patch("src.fetchers.gridstatus.asyncio.to_thread", AsyncMock(return_value=df)):
            records = await fetcher.fetch_rt_lmp(["HB_NORTH"], START, END)
        assert len(records) == 1

    async def test_record_shape(self):
        fetcher = self._fetcher()
        df = _make_rt_df(["HB_NORTH"], [42.5])
        with patch("src.fetchers.gridstatus.asyncio.to_thread", AsyncMock(return_value=df)):
            records = await fetcher.fetch_rt_lmp(["HB_NORTH"], START, END)
        r = records[0]
        assert r["iso"] == "ERCOT"
        assert r["node"] == "HB_NORTH"
        assert r["lmp"] == pytest.approx(42.5)
        assert "timestamp" in r

    async def test_timestamp_is_iso_format(self):
        fetcher = self._fetcher()
        df = _make_rt_df(["HB_NORTH"])
        with patch("src.fetchers.gridstatus.asyncio.to_thread", AsyncMock(return_value=df)):
            records = await fetcher.fetch_rt_lmp(["HB_NORTH"], START, END)
        # Should not raise
        from datetime import datetime
        datetime.fromisoformat(records[0]["timestamp"])

    async def test_node_filter_excludes_unmatched(self):
        fetcher = self._fetcher()
        df = _make_rt_df(["HB_NORTH", "HB_SOUTH"], [30.0, 35.0])
        with patch("src.fetchers.gridstatus.asyncio.to_thread", AsyncMock(return_value=df)):
            records = await fetcher.fetch_rt_lmp(["HB_NORTH"], START, END)
        assert len(records) == 1
        assert records[0]["node"] == "HB_NORTH"

    async def test_empty_node_list_returns_all_rows(self):
        """Empty nodes list means no filter — all rows returned."""
        fetcher = self._fetcher()
        df = _make_rt_df(["HB_NORTH", "HB_SOUTH"])
        with patch("src.fetchers.gridstatus.asyncio.to_thread", AsyncMock(return_value=df)):
            records = await fetcher.fetch_rt_lmp([], START, END)
        assert len(records) == 2

    async def test_empty_dataframe_returns_empty_list(self):
        fetcher = self._fetcher()
        df = pd.DataFrame()
        with patch("src.fetchers.gridstatus.asyncio.to_thread", AsyncMock(return_value=df)):
            records = await fetcher.fetch_rt_lmp(["HB_NORTH"], START, END)
        assert records == []

    async def test_congestion_defaults_to_zero_when_missing(self):
        fetcher = self._fetcher()
        df = _make_rt_df(["HB_NORTH"])
        with patch("src.fetchers.gridstatus.asyncio.to_thread", AsyncMock(return_value=df)):
            records = await fetcher.fetch_rt_lmp(["HB_NORTH"], START, END)
        assert records[0]["congestion"] == pytest.approx(0.0)

    async def test_loss_defaults_to_zero_when_missing(self):
        fetcher = self._fetcher()
        df = _make_rt_df(["HB_NORTH"])
        with patch("src.fetchers.gridstatus.asyncio.to_thread", AsyncMock(return_value=df)):
            records = await fetcher.fetch_rt_lmp(["HB_NORTH"], START, END)
        assert records[0]["loss"] == pytest.approx(0.0)

    async def test_energy_falls_back_to_lmp_when_column_missing(self):
        fetcher = self._fetcher()
        df = _make_rt_df(["HB_NORTH"], [55.0])
        with patch("src.fetchers.gridstatus.asyncio.to_thread", AsyncMock(return_value=df)):
            records = await fetcher.fetch_rt_lmp(["HB_NORTH"], START, END)
        assert records[0]["energy"] == pytest.approx(55.0)

    async def test_energy_uses_explicit_column_when_present(self):
        fetcher = self._fetcher()
        df = _make_rt_df(["HB_NORTH"], [30.0])
        df["Energy"] = 28.0
        with patch("src.fetchers.gridstatus.asyncio.to_thread", AsyncMock(return_value=df)):
            records = await fetcher.fetch_rt_lmp(["HB_NORTH"], START, END)
        assert records[0]["energy"] == pytest.approx(28.0)


# ── fetch_da_lmp ──────────────────────────────────────────────────────────────

class TestFetchDaLmp:
    def _fetcher(self) -> GridStatusFetcher:
        with patch("src.fetchers.gridstatus.GridStatusClient"):
            return GridStatusFetcher("ERCOT")

    async def test_happy_path_returns_records(self):
        fetcher = self._fetcher()
        df = _make_rt_df(["HB_NORTH"])
        with patch("src.fetchers.gridstatus.asyncio.to_thread", AsyncMock(return_value=df)):
            records = await fetcher.fetch_da_lmp(["HB_NORTH"], START, END)
        assert len(records) == 1

    async def test_iso_field_correct(self):
        fetcher = self._fetcher()
        df = _make_rt_df(["HB_NORTH"])
        with patch("src.fetchers.gridstatus.asyncio.to_thread", AsyncMock(return_value=df)):
            records = await fetcher.fetch_da_lmp(["HB_NORTH"], START, END)
        assert records[0]["iso"] == "ERCOT"

    async def test_node_filter_applied(self):
        fetcher = self._fetcher()
        df = _make_rt_df(["HB_NORTH", "HB_SOUTH"])
        with patch("src.fetchers.gridstatus.asyncio.to_thread", AsyncMock(return_value=df)):
            records = await fetcher.fetch_da_lmp(["HB_SOUTH"], START, END)
        assert len(records) == 1
        assert records[0]["node"] == "HB_SOUTH"

    async def test_empty_dataframe_returns_empty_list(self):
        fetcher = self._fetcher()
        df = pd.DataFrame()
        with patch("src.fetchers.gridstatus.asyncio.to_thread", AsyncMock(return_value=df)):
            records = await fetcher.fetch_da_lmp(["HB_NORTH"], START, END)
        assert records == []


# ── fetch_ancillary_prices ────────────────────────────────────────────────────

class TestFetchAncillaryPrices:
    def _fetcher(self) -> GridStatusFetcher:
        with patch("src.fetchers.gridstatus.GridStatusClient"):
            return GridStatusFetcher("ERCOT")

    async def test_happy_path_all_services(self):
        fetcher = self._fetcher()
        df = _make_as_df()
        with patch("src.fetchers.gridstatus.asyncio.to_thread", AsyncMock(return_value=df)):
            records = await fetcher.fetch_ancillary_prices(
                ["REG_UP", "REG_DOWN", "NONSPIN", "SPIN"], START, END
            )
        assert len(records) == 4

    async def test_service_filter_excludes_unrequested(self):
        fetcher = self._fetcher()
        df = _make_as_df()
        with patch("src.fetchers.gridstatus.asyncio.to_thread", AsyncMock(return_value=df)):
            records = await fetcher.fetch_ancillary_prices(["REG_UP"], START, END)
        assert len(records) == 1
        assert records[0]["service"] == "REG_UP"

    async def test_clearing_price_correct(self):
        fetcher = self._fetcher()
        df = _make_as_df()
        with patch("src.fetchers.gridstatus.asyncio.to_thread", AsyncMock(return_value=df)):
            records = await fetcher.fetch_ancillary_prices(["REG_UP"], START, END)
        assert records[0]["clearing_price"] == pytest.approx(5.0)

    async def test_mileage_is_none(self):
        fetcher = self._fetcher()
        df = _make_as_df()
        with patch("src.fetchers.gridstatus.asyncio.to_thread", AsyncMock(return_value=df)):
            records = await fetcher.fetch_ancillary_prices(["REG_UP"], START, END)
        assert records[0]["mileage"] is None

    async def test_iso_field_correct(self):
        fetcher = self._fetcher()
        df = _make_as_df()
        with patch("src.fetchers.gridstatus.asyncio.to_thread", AsyncMock(return_value=df)):
            records = await fetcher.fetch_ancillary_prices(["REG_DOWN"], START, END)
        assert records[0]["iso"] == "ERCOT"

    async def test_nan_values_skipped(self):
        fetcher = self._fetcher()
        df = _make_as_df()
        df.loc[0, "Regulation Up"] = np.nan
        with patch("src.fetchers.gridstatus.asyncio.to_thread", AsyncMock(return_value=df)):
            records = await fetcher.fetch_ancillary_prices(["REG_UP"], START, END)
        assert records == []

    async def test_empty_dataframe_returns_empty_list(self):
        fetcher = self._fetcher()
        df = pd.DataFrame()
        with patch("src.fetchers.gridstatus.asyncio.to_thread", AsyncMock(return_value=df)):
            records = await fetcher.fetch_ancillary_prices(["REG_UP"], START, END)
        assert records == []

    async def test_empty_services_list_returns_empty(self):
        fetcher = self._fetcher()
        df = _make_as_df()
        with patch("src.fetchers.gridstatus.asyncio.to_thread", AsyncMock(return_value=df)):
            records = await fetcher.fetch_ancillary_prices([], START, END)
        assert records == []


# ── ISO initialisation ────────────────────────────────────────────────────────

class TestInit:
    def test_iso_uppercased(self):
        with patch("src.fetchers.gridstatus.GridStatusClient"):
            fetcher = GridStatusFetcher("ercot")
        assert fetcher._iso == "ERCOT"

    def test_default_iso_is_ercot(self):
        with patch("src.fetchers.gridstatus.GridStatusClient"):
            fetcher = GridStatusFetcher()
        assert fetcher._iso == "ERCOT"

    def test_pjm_iso_accepted(self):
        with patch("src.fetchers.gridstatus.GridStatusClient"):
            fetcher = GridStatusFetcher("PJM")
        assert fetcher._iso == "PJM"

    def test_unsupported_iso_raises(self):
        with patch("src.fetchers.gridstatus.GridStatusClient"):
            with pytest.raises(ValueError, match="Unsupported ISO"):
                GridStatusFetcher("CAISO")


# ── PJM-specific behaviour ────────────────────────────────────────────────────

def _make_pjm_rt_df(locations: list[str], prices: list[float] | None = None) -> pd.DataFrame:
    if prices is None:
        prices = [40.0] * len(locations)
    return pd.DataFrame({
        "Interval Start": [pd.Timestamp("2024-01-15T01:00:00")] * len(locations),
        "Location": locations,
        "LMP": prices,
    })


class TestPjmFetchRtLmp:
    def _fetcher(self) -> GridStatusFetcher:
        with patch("src.fetchers.gridstatus.GridStatusClient"):
            return GridStatusFetcher("PJM")

    async def test_happy_path_returns_records(self):
        fetcher = self._fetcher()
        df = _make_pjm_rt_df(["AEP GEN HUB"])
        with patch("src.fetchers.gridstatus.asyncio.to_thread", AsyncMock(return_value=df)):
            records = await fetcher.fetch_rt_lmp(["AEP GEN HUB"], START, END)
        assert len(records) == 1

    async def test_iso_field_is_pjm(self):
        fetcher = self._fetcher()
        df = _make_pjm_rt_df(["AEP GEN HUB"])
        with patch("src.fetchers.gridstatus.asyncio.to_thread", AsyncMock(return_value=df)):
            records = await fetcher.fetch_rt_lmp(["AEP GEN HUB"], START, END)
        assert records[0]["iso"] == "PJM"

    async def test_node_mapped_from_location_column(self):
        fetcher = self._fetcher()
        df = _make_pjm_rt_df(["DOM HUB"])
        with patch("src.fetchers.gridstatus.asyncio.to_thread", AsyncMock(return_value=df)):
            records = await fetcher.fetch_rt_lmp([], START, END)
        assert records[0]["node"] == "DOM HUB"

    async def test_lmp_mapped_from_lmp_column(self):
        fetcher = self._fetcher()
        df = _make_pjm_rt_df(["AEP GEN HUB"], [55.5])
        with patch("src.fetchers.gridstatus.asyncio.to_thread", AsyncMock(return_value=df)):
            records = await fetcher.fetch_rt_lmp([], START, END)
        assert records[0]["lmp"] == pytest.approx(55.5)

    async def test_node_filter_works_for_pjm(self):
        fetcher = self._fetcher()
        df = _make_pjm_rt_df(["AEP GEN HUB", "DOM HUB"])
        with patch("src.fetchers.gridstatus.asyncio.to_thread", AsyncMock(return_value=df)):
            records = await fetcher.fetch_rt_lmp(["DOM HUB"], START, END)
        assert len(records) == 1
        assert records[0]["node"] == "DOM HUB"


class TestPjmAncillaryPrices:
    def _fetcher(self) -> GridStatusFetcher:
        with patch("src.fetchers.gridstatus.GridStatusClient"):
            return GridStatusFetcher("PJM")

    async def test_pjm_ancillary_returns_empty(self):
        """PJM ancillary not supported — should return [] without calling API."""
        fetcher = self._fetcher()
        to_thread_mock = AsyncMock()
        with patch("src.fetchers.gridstatus.asyncio.to_thread", to_thread_mock):
            records = await fetcher.fetch_ancillary_prices(["REG_UP"], START, END)
        assert records == []
        to_thread_mock.assert_not_called()

    async def test_pjm_ancillary_empty_services_also_returns_empty(self):
        fetcher = self._fetcher()
        with patch("src.fetchers.gridstatus.asyncio.to_thread", AsyncMock()):
            records = await fetcher.fetch_ancillary_prices([], START, END)
        assert records == []
