from datetime import date
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


async def fetch_grid_state(
    days: int = 2190, as_of_date: str | None = None
) -> pd.DataFrame:
    """Fetch ERCOT grid-state (wind, solar, load forecast/actual) for the last N days."""
    pool = _get_pool()
    if as_of_date:
        query = """
            SELECT time, wind_actual_mw, load_forecast_mw, load_actual_mw, solar_actual_mw
            FROM ercot_grid_state
            WHERE time < $1::date
              AND time >= $1::date - ($2 || ' days')::interval
            ORDER BY time ASC
        """
        as_of = date.fromisoformat(as_of_date)
        async with pool.acquire() as conn:
            rows: list[Any] = await conn.fetch(query, as_of, str(days))
    else:
        query = """
            SELECT time, wind_actual_mw, load_forecast_mw, load_actual_mw, solar_actual_mw
            FROM ercot_grid_state
            WHERE time >= NOW() - ($1 || ' days')::interval
            ORDER BY time ASC
        """
        async with pool.acquire() as conn:
            rows = await conn.fetch(query, str(days))

    if not rows:
        return pd.DataFrame(columns=["time", "wind_actual_mw", "load_forecast_mw", "load_actual_mw", "solar_actual_mw"])

    return pd.DataFrame([{
        "time": r["time"],
        "wind_actual_mw": r["wind_actual_mw"],
        "load_forecast_mw": r["load_forecast_mw"],
        "load_actual_mw": r["load_actual_mw"],
        "solar_actual_mw": r["solar_actual_mw"],
    } for r in rows])


async def fetch_gas_prices(
    days: int = 2190, as_of_date: str | None = None
) -> pd.DataFrame:
    """Fetch daily Henry Hub gas prices for the last N days."""
    pool = _get_pool()
    if as_of_date:
        query = """
            SELECT date, henry_hub
            FROM gas_prices
            WHERE date < $1::date
              AND date >= $1::date - ($2 || ' days')::interval
            ORDER BY date ASC
        """
        as_of = date.fromisoformat(as_of_date)
        async with pool.acquire() as conn:
            rows: list[Any] = await conn.fetch(query, as_of, str(days))
    else:
        query = """
            SELECT date, henry_hub
            FROM gas_prices
            WHERE date >= CURRENT_DATE - ($1 || ' days')::interval
            ORDER BY date ASC
        """
        async with pool.acquire() as conn:
            rows = await conn.fetch(query, str(days))

    if not rows:
        return pd.DataFrame(columns=["date", "henry_hub"])

    return pd.DataFrame([{"date": r["date"], "henry_hub": r["henry_hub"]} for r in rows])


async def fetch_lmp_history(
    iso: str, node: str, days: int = 90, as_of_date: str | None = None
) -> pd.DataFrame:
    pool = _get_pool()
    if as_of_date:
        # Strict upper bound: exclude the as_of date itself so the lag features
        # reflect only what would be known at midnight of the forecast day.
        # This prevents backtest leakage from same-day prices bleeding into lags.
        query = """
            SELECT time, lmp
            FROM lmp
            WHERE iso = $1
              AND node = $2
              AND time < $3::date
              AND time >= $3::date - ($4 || ' days')::interval
            ORDER BY time ASC
        """
        as_of = date.fromisoformat(as_of_date)
        async with pool.acquire() as conn:
            rows: list[Any] = await conn.fetch(query, iso, node, as_of, str(days))
    else:
        query = """
            SELECT time, lmp
            FROM lmp
            WHERE iso = $1
              AND node = $2
              AND time >= NOW() - ($3 || ' days')::interval
            ORDER BY time ASC
        """
        async with pool.acquire() as conn:
            rows = await conn.fetch(query, iso, node, str(days))

    if not rows:
        return pd.DataFrame(columns=["time", "lmp"])

    return pd.DataFrame([{"time": r["time"], "lmp": r["lmp"]} for r in rows])
