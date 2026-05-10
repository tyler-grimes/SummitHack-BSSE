"""
One-time backfill: load ERCOT hourly resource outage capacity from GridStatus.io
for 2020-01-01 → today, insert into ercot_outage_capacity table.

Usage:
    python scripts/backfill_outage_capacity.py [--start 2020-01-01] [--end 2026-05-10]
"""

import argparse
import asyncio
import logging
import os
from datetime import date, datetime, timedelta

import asyncpg
import pandas as pd
from dotenv import load_dotenv
from gridstatusio import GridStatusClient

load_dotenv()

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

_CHUNK_DAYS = 90


def _fetch_chunk(client: GridStatusClient, start: date, end: date) -> list[dict]:
    df: pd.DataFrame = client.get_dataset(
        "ercot_hourly_resource_outage_capacity_reports",
        start=start.isoformat(),
        end=end.isoformat(),
        limit=500_000,
    )
    if df is None or df.empty:
        return []

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
            "time":                  pd.Timestamp(row["interval_start_utc"]).to_pydatetime(),
            "total_outage_mw":       _mw("total_resource_mw"),
            "outage_mw_zone_north":  _mw("total_resource_mw_zone_north"),
            "outage_mw_zone_south":  _mw("total_resource_mw_zone_south"),
            "outage_mw_zone_west":   _mw("total_resource_mw_zone_west"),
            "outage_mw_zone_houston": _mw("total_resource_mw_zone_houston"),
        })
    return records


async def backfill(start: date, end: date) -> None:
    api_key = os.environ["GRIDSTATUS_API_KEY"]
    client = GridStatusClient(api_key=api_key)

    pool = await asyncpg.create_pool(
        host=os.getenv("POSTGRES_HOST", "localhost"),
        port=int(os.getenv("POSTGRES_PORT", "5432")),
        database=os.getenv("POSTGRES_DB", "energy_trading"),
        user=os.getenv("POSTGRES_USER", "postgres"),
        password=os.getenv("POSTGRES_PASSWORD", "postgres"),
        min_size=1,
        max_size=5,
    )

    try:
        current = start
        total_inserted = 0

        while current < end:
            chunk_end = min(current + timedelta(days=_CHUNK_DAYS), end)
            logger.info("Fetching %s → %s", current, chunk_end)
            try:
                records = await asyncio.to_thread(_fetch_chunk, client, current, chunk_end)
                if records:
                    async with pool.acquire() as conn:
                        await conn.executemany(
                            """
                            INSERT INTO ercot_outage_capacity
                                (time, total_outage_mw, outage_mw_zone_north, outage_mw_zone_south,
                                 outage_mw_zone_west, outage_mw_zone_houston)
                            VALUES ($1, $2, $3, $4, $5, $6)
                            ON CONFLICT DO NOTHING
                            """,
                            [(r["time"], r["total_outage_mw"], r["outage_mw_zone_north"],
                              r["outage_mw_zone_south"], r["outage_mw_zone_west"],
                              r["outage_mw_zone_houston"]) for r in records],
                        )
                    total_inserted += len(records)
                logger.info("  %d records (total: %d)", len(records), total_inserted)
            except Exception:
                logger.exception("  Failed for %s → %s — skipping", current, chunk_end)
            current = chunk_end + timedelta(days=1)

        logger.info("Backfill complete. Total records: %d", total_inserted)
    finally:
        await pool.close()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--start", default="2020-01-01")
    parser.add_argument("--end", default=str(date.today()))
    args = parser.parse_args()
    asyncio.run(backfill(date.fromisoformat(args.start), date.fromisoformat(args.end)))


if __name__ == "__main__":
    main()
