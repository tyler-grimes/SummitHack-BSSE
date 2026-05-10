import logging
import time
from datetime import date
from typing import Any

from ..config import config
from ..models import ErcotDamRecord, ErcotDamResponse, ErcotSppRecord, ErcotSppResponse
from .base import BaseFetcher

logger = logging.getLogger(__name__)

_RT_LMP_PATH = "np6-905-cd/spp_node_zone_hub"
_DA_LMP_PATH = "np4-190-cd/dam_stlmnt_pnt_prices"
_AS_DAM_PATH = "np4-188-cd/dam_clrng_prc_cpcty"
_AS_RTD_PATH = "np6-329-cd/rtd_ind_rtm_mcpc"

_OAUTH_SCOPE = (
    "openid "
    "fec253ea-0d06-4272-a5e6-b478baeecd70 "
    "offline_access"
)


class ErcotFetcher(BaseFetcher):
    """Fetches LMP and ancillary prices from ERCOT public API."""

    def __init__(self) -> None:
        super().__init__()
        self._token: str | None = None
        self._token_expires_at: float = 0.0

    async def _auth_headers(self) -> dict[str, str]:
        if time.time() >= self._token_expires_at - 60:
            await self._refresh_token()
        return {
            "Authorization": f"Bearer {self._token}",
            "Ocp-Apim-Subscription-Key": config.ercot_subscription_key,
        }

    async def _refresh_token(self) -> None:
        response = await self.client.post(
            config.ercot_auth_endpoint,
            data={
                "username": config.ercot_username,
                "password": config.ercot_password,
                "grant_type": "password",
                "scope": _OAUTH_SCOPE,
                "client_id": config.ercot_client_id,
                "response_type": "id_token",
            },
        )
        response.raise_for_status()
        payload: dict[str, Any] = response.json()
        self._token = str(payload["id_token"])
        self._token_expires_at = time.time() + int(payload.get("expires_in", 3600))
        logger.info("ERCOT token refreshed, expires in %ss", payload.get("expires_in"))

    async def _get_all_pages(self, path: str, params: dict[str, Any]) -> list[dict[str, Any]]:
        url = f"{config.ercot_base_url}/{path}"
        records: list[dict[str, Any]] = []
        page = 1

        while True:
            # Refresh headers each page — token expires in 3600s, multi-page fetches can be slow
            headers = await self._auth_headers()
            data = await self._get(url, params={**params, "page": page}, headers=headers)
            records.extend(data.get("data", []))
            meta = data.get("_meta", {})
            total_pages = meta.get("totalPages", 1)
            if page >= total_pages:
                break
            page += 1

        return records

    async def fetch_rt_lmp(self, nodes: list[str], start: date, end: date) -> list[dict[str, Any]]:
        results: list[dict[str, Any]] = []
        for node in nodes:
            raw = await self._get_all_pages(
                _RT_LMP_PATH,
                {
                    "deliveryDateFrom": start.isoformat(),
                    "deliveryDateTo": end.isoformat(),
                    "settlementPoint": node,
                },
            )
            parsed = ErcotSppResponse.model_validate(_wrap_ercot_response(raw))
            results.extend(_spp_to_dict(r, "ERCOT") for r in parsed.data)
        return results

    async def fetch_da_lmp(self, nodes: list[str], start: date, end: date) -> list[dict[str, Any]]:
        results: list[dict[str, Any]] = []
        for node in nodes:
            raw = await self._get_all_pages(
                _DA_LMP_PATH,
                {
                    "deliveryDateFrom": start.isoformat(),
                    "deliveryDateTo": end.isoformat(),
                    "settlementPoint": node,
                },
            )
            parsed = ErcotDamResponse.model_validate(_wrap_ercot_response(raw))
            results.extend(_dam_to_dict(r, "ERCOT") for r in parsed.data)
        return results

    async def fetch_ancillary_prices(
        self, services: list[str], start: date, end: date
    ) -> list[dict[str, Any]]:
        raw = await self._get_all_pages(
            _AS_DAM_PATH,
            {"deliveryDateFrom": start.isoformat(), "deliveryDateTo": end.isoformat()},
        )
        return [
            {
                # Full ISO 8601 timestamp — bare date rejected by TimescaleDB time column
                "timestamp": (
                    f"{r.get('deliveryDate')}"
                    f"T{(int(r.get('deliveryHour', 1)) - 1):02d}:00:00+00:00"
                ),
                "iso": "ERCOT",
                "service": r.get("ancillaryType"),
                "clearing_price": r.get("mcpc"),
                "mileage": None,
            }
            for r in raw
            if r.get("ancillaryType") in services
        ]


def _wrap_ercot_response(data: list[dict[str, Any]]) -> dict[str, Any]:
    n = len(data)
    return {
        "_meta": {"totalRecords": n, "pageSize": n, "totalPages": 1, "currentPage": 1},
        "data": data,
    }


def _spp_to_dict(r: ErcotSppRecord, iso: str) -> dict[str, Any]:
    hour = r.delivery_hour - 1
    interval_minutes = (r.delivery_interval - 1) * 15
    timestamp = f"{r.delivery_date}T{hour:02d}:{interval_minutes:02d}:00+00:00"
    return {
        "timestamp": timestamp,
        "iso": iso,
        "node": r.settlement_point,
        "lmp": r.settlement_point_price,
        "energy": r.settlement_point_price,
        "congestion": 0.0,
        "loss": 0.0,
    }


def _dam_to_dict(r: ErcotDamRecord, iso: str) -> dict[str, Any]:
    hour = r.delivery_hour - 1
    timestamp = f"{r.delivery_date}T{hour:02d}:00:00+00:00"
    return {
        "timestamp": timestamp,
        "iso": iso,
        "node": r.settlement_point,
        "lmp": r.settlement_point_price,
        "energy": r.settlement_point_price,
        "congestion": 0.0,
        "loss": 0.0,
    }
