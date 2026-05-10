"""
Seed 15 months of ERCOT RT LMP data (Jan 2025 – Mar 2026) for 4 hubs.

Fetches weekly chunks via GridStatus.io and inserts into TimescaleDB.
Run from repo root:
  cd /mnt/c/Users/tygri/energy-trading-optimization
  packages/data-pipeline/.venv/bin/python scripts/seed_historical.py
"""

import asyncio
import logging
import sys
import os
from datetime import date, timedelta

# Resolve project root; add data-pipeline package root so relative imports work
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "packages", "data-pipeline"))

from dotenv import load_dotenv
load_dotenv(os.path.join(ROOT, ".env"))

from src.db import init_pool, close_pool, insert_lmp_batch
from src.fetchers.gridstatus import GridStatusFetcher

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger(__name__)

HUBS = ["HB_NORTH", "HB_SOUTH", "HB_WEST", "HB_HOUSTON"]
START = date(2020, 1, 1)
END   = date(2026, 5, 9)  # up to yesterday
CHUNK = timedelta(days=7)   # one week per API call


def date_chunks(start: date, end: date, step: timedelta):
    cur = start
    while cur <= end:
        yield cur, min(cur + step - timedelta(days=1), end)
        cur += step


async def seed_hub(fetcher: GridStatusFetcher, hub: str) -> int:
    total = 0
    chunks = list(date_chunks(START, END, CHUNK))
    for i, (chunk_start, chunk_end) in enumerate(chunks):
        try:
            records = await fetcher.fetch_rt_lmp([hub], chunk_start, chunk_end)
            if records:
                inserted = await insert_lmp_batch(records)
                total += inserted
            log.info(
                "[%s] %d/%d  %s→%s  +%d rows (total %d)",
                hub, i + 1, len(chunks), chunk_start, chunk_end,
                len(records), total,
            )
        except Exception as exc:
            log.warning("[%s] chunk %s→%s failed: %s", hub, chunk_start, chunk_end, exc)
        # GridStatus free tier: 20 req/min → ~3s between calls
        await asyncio.sleep(3)
    return total


async def main() -> None:
    log.info("Connecting to DB...")
    await init_pool()

    fetcher = GridStatusFetcher(iso="ERCOT")
    grand_total = 0
    for hub in HUBS:
        log.info("=== Seeding %s (%s → %s) ===", hub, START, END)
        n = await seed_hub(fetcher, hub)
        log.info("=== %s done: %d rows ===", hub, n)
        grand_total += n

    await close_pool()
    log.info("Done. Total rows inserted: %d", grand_total)


if __name__ == "__main__":
    asyncio.run(main())
