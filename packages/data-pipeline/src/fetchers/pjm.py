import logging
from datetime import UTC, date, datetime
from typing import Any

from ..config import config
from ..models import PjmAncillaryRecord, PjmDaLmpRecord, PjmRtLmpRecord
from .base import BaseFetcher

logger = logging.getLogger(__name__)


class PjmFetcher(BaseFetcher):
    """Fetches LMP and ancillary prices from PJM Data Miner 2 API."""

    def _headers(self) -> dict[str, str]:
        return {"Ocp-Apim-Subscription-Key": config.pjm_subscription_key}

    async def _get_paginated(self, endpoint: str, params: dict[str, Any]) -> list[dict[str, Any]]:
        url = f"{config.pjm_base_url}/{endpoint}"
        records: list[dict[str, Any]] = []
        start_row = 1

        while True:
            page_params: dict[str, Any] = {
                **params,
                "rowCount": config.pjm_page_size,
                "startRow": start_row,
            }
            data = await self._get(url, params=page_params, headers=self._headers())
            batch: list[dict[str, Any]] = data if isinstance(data, list) else data.get("items", [])
            records.extend(batch)

            # Use API-reported total if available to avoid extra empty request
            # on exact page boundary
            total_rows: int | None = data.get("totalRows") if isinstance(data, dict) else None
            if total_rows is not None:
                if len(records) >= total_rows:
                    break
            elif len(batch) < config.pjm_page_size:
                break

            start_row += len(batch)

        return records

    async def fetch_rt_lmp(self, nodes: list[str], start: date, end: date) -> list[dict[str, Any]]:
        raw = await self._get_paginated(
            "rt_hrl_lmps",
            {
                "datetime_beginning_utc_gte": _utc_str(start),
                "datetime_beginning_utc_lte": _utc_str(end),
                "pnode_name": ";".join(nodes) if nodes else "",
            },
        )
        return [_rt_to_dict(PjmRtLmpRecord.model_validate(r)) for r in raw]

    async def fetch_da_lmp(self, nodes: list[str], start: date, end: date) -> list[dict[str, Any]]:
        raw = await self._get_paginated(
            "da_hrl_lmps",
            {
                "datetime_beginning_utc_gte": _utc_str(start),
                "datetime_beginning_utc_lte": _utc_str(end),
                "pnode_name": ";".join(nodes) if nodes else "",
            },
        )
        return [_da_to_dict(PjmDaLmpRecord.model_validate(r)) for r in raw]

    async def fetch_ancillary_prices(
        self, services: list[str], start: date, end: date
    ) -> list[dict[str, Any]]:
        raw = await self._get_paginated(
            "ancillary_services",
            {
                "datetime_beginning_utc_gte": _utc_str(start),
                "datetime_beginning_utc_lte": _utc_str(end),
            },
        )
        return [
            _ancillary_to_dict(PjmAncillaryRecord.model_validate(r))
            for r in raw
            if r.get("ancillary_service") in services
        ]


def _utc_str(d: date) -> str:
    return datetime(d.year, d.month, d.day, tzinfo=UTC).isoformat()


def _rt_to_dict(r: PjmRtLmpRecord) -> dict[str, Any]:
    return {
        "timestamp": r.datetime_beginning_utc.isoformat(),
        "iso": "PJM",
        "node": r.pnode_name,
        "lmp": r.total_lmp_rt,
        "energy": r.system_energy_price_rt,
        "congestion": r.congestion_price_rt,
        "loss": r.marginal_loss_price_rt,
    }


def _da_to_dict(r: PjmDaLmpRecord) -> dict[str, Any]:
    return {
        "timestamp": r.datetime_beginning_utc.isoformat(),
        "iso": "PJM",
        "node": r.pnode_name,
        "lmp": r.total_lmp_da,
        "energy": r.system_energy_price_da,
        "congestion": r.congestion_price_da,
        "loss": r.marginal_loss_price_da,
    }


def _ancillary_to_dict(r: PjmAncillaryRecord) -> dict[str, Any]:
    return {
        "timestamp": r.datetime_beginning_utc.isoformat(),
        "iso": "PJM",
        "service": r.ancillary_service,
        "clearing_price": r.value,
        "mileage": None,
    }
