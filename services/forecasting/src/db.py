from typing import Any

import asyncpg
import pandas as pd

from .config import settings

_pool: asyncpg.Pool | None = None


async def init_pool() -> None:
    global _pool
    _pool = await asyncpg.create_pool(
        host=settings.postgres_host,
        port=settings.postgres_port,
        database=settings.postgres_db,
        user=settings.postgres_user,
        password=settings.postgres_password,
        min_size=2,
        max_size=10,
    )


async def close_pool() -> None:
    global _pool
    if _pool is not None:
        await _pool.close()
        _pool = None


def _get_pool() -> asyncpg.Pool:
    if _pool is None:
        raise RuntimeError("Database pool is not initialized. Call init_pool() first.")
    return _pool


async def fetch_lmp_history(iso: str, node: str, days: int = 90) -> pd.DataFrame:
    pool = _get_pool()
    query = """
        SELECT time, lmp
        FROM lmp
        WHERE iso = $1
          AND node = $2
          AND time >= NOW() - ($3 || ' days')::interval
        ORDER BY time ASC
    """
    async with pool.acquire() as conn:
        rows: list[Any] = await conn.fetch(query, iso, node, str(days))

    if not rows:
        return pd.DataFrame(columns=["time", "lmp"])

    return pd.DataFrame([{"time": r["time"], "lmp": r["lmp"]} for r in rows])
