"""GridStatus.io fetcher — real LMP + ancillary data for ERCOT and PJM.

Requires GRIDSTATUS_API_KEY env var. Free tier: 1M rows/month, 20 req/min.
Uses the gridstatusio SDK which returns pandas DataFrames; calls are run in a
thread to avoid blocking the async event loop.

PJM ancillary service prices are not available via GridStatus — fetch_ancillary_prices
returns [] for PJM with a warning.
"""

import asyncio
import logging
from datetime import date
from typing import Any

import pandas as pd
from gridstatusio import GridStatusClient

from ..config import config
from .base import BaseFetcher

logger = logging.getLogger(__name__)

# Per-ISO dataset names and column mappings for the GridStatus.io API.
# Column names verified against live API responses 2026-05-09.
_ISO_CONFIG: dict[str, dict[str, str]] = {
    "ERCOT": {
        "rt_lmp": "ercot_lmp_by_settlement_point",
        "da_lmp": "ercot_lmp_by_bus_dam",
        "as_prices": "ercot_as_prices",
        "col_node": "location",
        "col_lmp": "lmp",
    },
    "PJM": {
        "rt_lmp": "pjm_lmp_real_time_5_min",
        "da_lmp": "pjm_lmp_day_ahead_hourly",
        "as_prices": "",  # Not available via GridStatus
        "col_node": "location",
        "col_lmp": "lmp",
    },
}

# ERCOT ancillary service column names → canonical service keys
_ERCOT_AS_COL_MAP: dict[str, str] = {
    "regulation_up": "REG_UP",
    "regulation_down": "REG_DOWN",
    "non_spinning_reserves": "NONSPIN",
    "responsive_reserves": "SPIN",
}


class GridStatusFetcher(BaseFetcher):
    """Fetches LMP and ancillary prices from GridStatus.io for ERCOT and PJM."""

    def __init__(self, iso: str = "ERCOT") -> None:
        super().__init__()
        self._iso = iso.upper()
        if self._iso not in _ISO_CONFIG:
            raise ValueError(f"Unsupported ISO: {self._iso}. Supported: {list(_ISO_CONFIG)}")
        self._gs_client = GridStatusClient(api_key=config.gridstatus_api_key)

    async def __aenter__(self) -> "GridStatusFetcher":
        return self

    async def __aexit__(self, *_: object) -> None:
        pass

    def _get_dataset(self, dataset: str, **kwargs: object) -> pd.DataFrame:
        """Synchronous SDK call — run via asyncio.to_thread."""
        return self._gs_client.get_dataset(dataset, **kwargs)

    def _iso_cfg(self) -> dict[str, str]:
        return _ISO_CONFIG[self._iso]

    def _normalize_lmp_df(self, df: pd.DataFrame) -> pd.DataFrame:
        cfg = self._iso_cfg()
        return df.rename(columns={
            "interval_start_utc": "time",
            cfg["col_node"]: "node",
            cfg["col_lmp"]: "lmp",
        })

    def _df_to_lmp_records(self, df: pd.DataFrame) -> list[dict[str, Any]]:
        records = []
        for _, row in df.iterrows():
            lmp_val = float(row["lmp"])
            records.append({
                "timestamp": pd.Timestamp(row["time"]).isoformat(),
                "iso": self._iso,
                "node": str(row["node"]),
                "lmp": lmp_val,
                "energy": float(row.get("energy", lmp_val)),
                "congestion": float(row.get("congestion", 0.0)),
                "loss": float(row.get("loss", 0.0)),
            })
        return records

    async def fetch_rt_lmp(
        self, nodes: list[str], start: date, end: date
    ) -> list[dict[str, Any]]:
        df: pd.DataFrame = await asyncio.to_thread(
            self._get_dataset,
            self._iso_cfg()["rt_lmp"],
            start=start.isoformat(),
            end=end.isoformat(),
            limit=100_000,
        )

        if df.empty:
            logger.warning("GridStatus returned empty RT LMP DataFrame for %s", self._iso)
            return []

        df = self._normalize_lmp_df(df)
        if nodes:
            df = df[df["node"].isin(nodes)]

        records = self._df_to_lmp_records(df)
        logger.info("GridStatus RT LMP: %d records for %s", len(records), self._iso)
        return records

    async def fetch_da_lmp(
        self, nodes: list[str], start: date, end: date
    ) -> list[dict[str, Any]]:
        df: pd.DataFrame = await asyncio.to_thread(
            self._get_dataset,
            self._iso_cfg()["da_lmp"],
            start=start.isoformat(),
            end=end.isoformat(),
            limit=100_000,
        )

        if df.empty:
            logger.warning("GridStatus returned empty DA LMP DataFrame for %s", self._iso)
            return []

        df = self._normalize_lmp_df(df)
        if nodes:
            df = df[df["node"].isin(nodes)]

        records = self._df_to_lmp_records(df)
        logger.info("GridStatus DA LMP: %d records for %s", len(records), self._iso)
        return records

    async def fetch_outage_capacity(
        self, start: date, end: date
    ) -> list[dict[str, Any]]:
        """Fetch hourly resource outage capacity for ERCOT only."""
        if self._iso != "ERCOT":
            return []

        df: pd.DataFrame = await asyncio.to_thread(
            self._get_dataset,
            "ercot_hourly_resource_outage_capacity_reports",
            start=start.isoformat(),
            end=end.isoformat(),
            limit=500_000,
        )

        if df.empty:
            logger.warning("GridStatus returned empty outage capacity DataFrame")
            return []

        # Multiple publish times exist per interval — keep latest published value.
        df = (
            df.sort_values("publish_time_utc")
            .groupby("interval_start_utc", as_index=False)
            .last()
        )

        records = []
        for _, row in df.iterrows():
            def _mw(col: str) -> float:
                v = row.get(col)
                return float(v) if v is not None and not (isinstance(v, float) and v != v) else 0.0

            records.append({
                "timestamp": pd.Timestamp(row["interval_start_utc"]).isoformat(),
                "total_outage_mw":        _mw("total_resource_mw"),
                "outage_mw_zone_north":   _mw("total_resource_mw_zone_north"),
                "outage_mw_zone_south":   _mw("total_resource_mw_zone_south"),
                "outage_mw_zone_west":    _mw("total_resource_mw_zone_west"),
                "outage_mw_zone_houston": _mw("total_resource_mw_zone_houston"),
            })

        logger.info("GridStatus outage capacity: %d hourly records", len(records))
        return records

    async def fetch_ancillary_prices(
        self, services: list[str], start: date, end: date
    ) -> list[dict[str, Any]]:
        if not self._iso_cfg()["as_prices"]:
            logger.warning(
                "GridStatus ancillary prices not supported for %s — returning empty", self._iso
            )
            return []

        df: pd.DataFrame = await asyncio.to_thread(
            self._get_dataset,
            self._iso_cfg()["as_prices"],
            start=start.isoformat(),
            end=end.isoformat(),
            limit=50_000,
        )

        if df.empty:
            logger.warning("GridStatus returned empty AS DataFrame for %s", self._iso)
            return []

        records = []
        for _, row in df.iterrows():
            ts = pd.Timestamp(row["interval_start_utc"]).isoformat()
            for gs_col, service_key in _ERCOT_AS_COL_MAP.items():
                if service_key not in services:
                    continue
                if gs_col not in row or pd.isna(row[gs_col]):
                    continue
                records.append({
                    "timestamp": ts,
                    "iso": self._iso,
                    "service": service_key,
                    "clearing_price": float(row[gs_col]),
                    "mileage": None,
                })

        logger.info("GridStatus AS: %d records for %s", len(records), self._iso)
        return records
