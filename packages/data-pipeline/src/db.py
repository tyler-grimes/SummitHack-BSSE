import logging
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from datetime import datetime
from typing import Any

import asyncpg

from .config import config

logger = logging.getLogger(__name__)

_pool: asyncpg.Pool | None = None


async def init_pool() -> None:
    global _pool
    _pool = await asyncpg.create_pool(
        host=config.postgres_host,
        port=config.postgres_port,
        database=config.postgres_db,
        user=config.postgres_user,
        password=config.postgres_password,
        min_size=2,
        max_size=10,
    )
    logger.info("DB pool initialized")


async def close_pool() -> None:
    global _pool
    if _pool:
        await _pool.close()
        _pool = None


@asynccontextmanager
async def acquire() -> AsyncGenerator[asyncpg.Connection, None]:
    if _pool is None:
        raise RuntimeError("Call init_pool() first")
    async with _pool.acquire() as conn:
        yield conn


def _to_dt(ts: object) -> datetime:
    if isinstance(ts, datetime):
        return ts
    return datetime.fromisoformat(str(ts))


async def insert_lmp_batch(records: list[dict[str, Any]]) -> int:
    """Bulk-insert LMP records. Returns count inserted."""
    if not records:
        return 0
    async with acquire() as conn:
        await conn.executemany(
            """
            INSERT INTO lmp (time, iso, node, lmp, energy, congestion, loss)
            VALUES ($1, $2, $3, $4, $5, $6, $7)
            ON CONFLICT DO NOTHING
            """,
            [
                (
                    _to_dt(r["timestamp"]),
                    r["iso"],
                    r["node"],
                    r["lmp"],
                    r.get("energy", 0.0),
                    r.get("congestion", 0.0),
                    r.get("loss", 0.0),
                )
                for r in records
            ],
        )
    return len(records)


async def insert_ancillary_batch(records: list[dict[str, Any]]) -> int:
    """Bulk-insert ancillary price records. Returns count inserted."""
    if not records:
        return 0
    async with acquire() as conn:
        await conn.executemany(
            """
            INSERT INTO ancillary_prices (time, iso, service, clearing_price, mileage)
            VALUES ($1, $2, $3, $4, $5)
            ON CONFLICT DO NOTHING
            """,
            [
                (
                    _to_dt(r["timestamp"]),
                    r["iso"],
                    r["service"],
                    r["clearing_price"],
                    r.get("mileage"),
                )
                for r in records
            ],
        )
    return len(records)
