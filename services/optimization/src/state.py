import json
import logging
from typing import Any

import redis

from . import config
from .battery import BatteryParams

_log = logging.getLogger(__name__)


def get_battery_params(asset_id: str) -> BatteryParams:
    try:
        client: redis.Redis = redis.Redis(
            host=config.REDIS_HOST,
            port=config.REDIS_PORT,
            password=config.REDIS_PASSWORD,
            decode_responses=True,
            socket_connect_timeout=2,
        )
        raw = client.get(f"battery:{asset_id}")
        if raw is not None:
            data: dict[str, Any] = json.loads(str(raw))
            data["asset_id"] = asset_id
            return BatteryParams(**data)
    except Exception as exc:
        _log.debug("Redis unavailable for asset %s: %s", asset_id, exc)
    return BatteryParams(asset_id=asset_id)
