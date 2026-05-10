"""GridStatus.io fetcher — real LMP + ancillary data for ERCOT (and others).

Requires GRIDSTATUS_API_KEY env var. Free tier: 1M rows/month, 20 req/min.
Uses the gridstatusio SDK which returns pandas DataFrames; calls are run in a
thread to avoid blocking the async event loop.
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

# GridStatus dataset names
_ERCOT_RT_LMP = "ercot_real_time_price_by_settlement_point"
_ERCOT_DA_LMP = "ercot_settlement_point_prices"
_ERCOT_AS_PRICES = "ercot_ancillary_service_prices"

# Map GridStatus ancillary column names → our service keys
_AS_COL_MAP: dict[str, str] = {
    "Regulation Up": "REG_UP",
    "Regulation Down": "REG_DOWN",
    "Non-Spinning Reserves": "NONSPIN",
    "Responsive Reserves": "SPIN",
}


class GridStatusFetcher(BaseFetcher):
    """Fetches LMP and ancillary prices from GridStatus.io for ERCOT."""

    def __init__(self, iso: str = "ERCOT") -> None:
        super().__init__()
        self._iso = iso.upper()
        self._client = GridStatusClient(api_key=config.gridstatus_api_key)

    def _get_dataset(self, dataset: str, **kwargs: object) -> pd.DataFrame:
        """Synchronous SDK call — run via asyncio.to_thread."""
        return self._client.get_dataset(dataset, **kwargs)  # type: ignore[union-attr]

    async def fetch_rt_lmp(
        self, nodes: list[str], start: date, end: date
    ) -> list[dict[str, Any]]:
        df: pd.DataFrame = await asyncio.to_thread(
            self._get_dataset,
            _ERCOT_RT_LMP,
            start=start.isoformat(),
            end=end.isoformat(),
            limit=100_000,
        )

        if df.empty:
            logger.warning("GridStatus returned empty RT LMP DataFrame for %s", self._iso)
            return []

        df = df.rename(columns={
            "Interval Start": "time",
            "Settlement Point": "node",
            "Settlement Point Price": "lmp",
        })

        if nodes:
            df = df[df["node"].isin(nodes)]

        records = []
        for _, row in df.iterrows():
            records.append({
                "timestamp": pd.Timestamp(row["time"]).isoformat(),
                "iso": self._iso,
                "node": str(row["node"]),
                "lmp": float(row["lmp"]),
                "energy": float(row.get("Energy", row["lmp"])),
                "congestion": float(row.get("Congestion", 0.0)),
                "loss": float(row.get("Loss", 0.0)),
            })

        logger.info("GridStatus RT LMP: %d records for %s", len(records), self._iso)
        return records

    async def fetch_da_lmp(
        self, nodes: list[str], start: date, end: date
    ) -> list[dict[str, Any]]:
        df: pd.DataFrame = await asyncio.to_thread(
            self._get_dataset,
            _ERCOT_DA_LMP,
            start=start.isoformat(),
            end=end.isoformat(),
            limit=100_000,
        )

        if df.empty:
            logger.warning("GridStatus returned empty DA LMP DataFrame for %s", self._iso)
            return []

        # DA dataset uses same column shape as RT for ERCOT
        df = df.rename(columns={
            "Interval Start": "time",
            "Settlement Point": "node",
            "Settlement Point Price": "lmp",
        })

        if nodes:
            df = df[df["node"].isin(nodes)]

        records = []
        for _, row in df.iterrows():
            records.append({
                "timestamp": pd.Timestamp(row["time"]).isoformat(),
                "iso": self._iso,
                "node": str(row["node"]),
                "lmp": float(row["lmp"]),
                "energy": float(row.get("Energy", row["lmp"])),
                "congestion": float(row.get("Congestion", 0.0)),
                "loss": float(row.get("Loss", 0.0)),
            })

        logger.info("GridStatus DA LMP: %d records for %s", len(records), self._iso)
        return records

    async def fetch_ancillary_prices(
        self, services: list[str], start: date, end: date
    ) -> list[dict[str, Any]]:
        df: pd.DataFrame = await asyncio.to_thread(
            self._get_dataset,
            _ERCOT_AS_PRICES,
            start=start.isoformat(),
            end=end.isoformat(),
            limit=50_000,
        )

        if df.empty:
            logger.warning("GridStatus returned empty AS DataFrame for %s", self._iso)
            return []

        records = []
        for _, row in df.iterrows():
            ts = pd.Timestamp(row["Interval Start"]).isoformat()
            for gs_col, service_key in _AS_COL_MAP.items():
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
