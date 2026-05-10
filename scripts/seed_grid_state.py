"""
Seed ERCOT grid-state signals (wind actual/forecast + system load) into
the ercot_grid_state TimescaleDB table using the GridStatus.io API.

Source: ercot_standardized_hourly — one deduplicated row per hour containing:
  - fuel_mix.wind                  → wind_actual_mw (MW)
  - fuel_mix.solar                 → solar_actual_mw (MW)
  - load_forecast.load_forecast    → load_forecast_mw (DA load forecast, MW)
  - load.load                      → load_actual_mw (MW)

Derived features in model:
  - load_deviation_mw = load_actual_mw - load_forecast_mw  (demand surprise → spike risk)
  - wind_ramp_mw      = wind[t] - wind[t-1]                (wind drop → spike risk)

The free-tier API returns 50k rows sorted oldest-first and ignores date
filters.  We fetch twice:
  - Pass 1 (asc):  covers 2017-01-01 → ~2022-09
  - Pass 2 (desc): covers ~2020-09 → present
Together they cover all of 2020-2026 with some overlap; ON CONFLICT handles it.

~100k rows total, well within the 500k quota.

Usage:
    GRIDSTATUS_API_KEY=<key> python scripts/seed_grid_state.py
"""

import asyncio
import logging
import os
from datetime import datetime, timezone

import asyncpg
import httpx

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

GRIDSTATUS_KEY  = os.environ.get("GRIDSTATUS_API_KEY", "")
GRIDSTATUS_BASE = "https://api.gridstatus.io/v1/datasets"
DATASET         = "ercot_standardized_hourly"

# Only keep rows in this window
SEED_START = datetime(2020, 1, 1, tzinfo=timezone.utc)
SEED_END   = datetime(2026, 5, 9, tzinfo=timezone.utc)   # up to last full LMP day

PG_HOST = os.environ.get("POSTGRES_HOST", "localhost")
PG_PORT = int(os.environ.get("POSTGRES_PORT", "5432"))
PG_DB   = os.environ.get("POSTGRES_DB", "energy_trading")
PG_USER = os.environ.get("POSTGRES_USER", "postgres")
PG_PASS = os.environ.get("POSTGRES_PASSWORD", "postgres_energy_password")

PAGE_SIZE    = 50_000
INSERT_BATCH = 5_000
RATE_SLEEP   = 1.2   # GridStatus: 1 req/sec on free tier

# ---------------------------------------------------------------------------
# Fetch
# ---------------------------------------------------------------------------

async def fetch_pass(client: httpx.AsyncClient, order: str) -> list[dict]:
    """Fetch one 50k-row pass, sorted by order ('asc' or 'desc')."""
    url    = f"{GRIDSTATUS_BASE}/{DATASET}/query"
    params = {"limit": PAGE_SIZE, "order": order}

    log.info("  Fetching %s order=%s ...", DATASET, order)
    await asyncio.sleep(RATE_SLEEP)
    resp = await client.get(url, params=params, timeout=300)
    resp.raise_for_status()
    body = resp.json()

    rows = body.get("data", [])
    log.info("  Got %d rows", len(rows))
    if rows:
        log.info("  Range: %s → %s", rows[0]["interval_start_utc"], rows[-1]["interval_start_utc"])
    return rows


def parse_rows(rows: list[dict]) -> dict[datetime, tuple]:
    """Return {timestamp: (wind_mw, load_forecast_mw, load_actual_mw, solar_mw)} for rows
    within [SEED_START, SEED_END).
    """
    out: dict[datetime, tuple] = {}
    for r in rows:
        ts_str = r.get("interval_start_utc")
        if not ts_str:
            continue
        t = datetime.fromisoformat(ts_str)
        if t.tzinfo is None:
            t = t.replace(tzinfo=timezone.utc)

        if t < SEED_START or t >= SEED_END:
            continue

        wind   = r.get("fuel_mix.wind")
        solar  = r.get("fuel_mix.solar")
        load_f = r.get("load_forecast.load_forecast")
        load_a = r.get("load.load")

        out[t] = (
            float(wind)   if wind   is not None else None,
            float(load_f) if load_f is not None else None,
            float(load_a) if load_a is not None else None,
            float(solar)  if solar  is not None else None,
        )
    return out


# ---------------------------------------------------------------------------
# DB
# ---------------------------------------------------------------------------

UPSERT_SQL = """
INSERT INTO ercot_grid_state (time, wind_actual_mw, load_forecast_mw, load_actual_mw, solar_actual_mw)
VALUES ($1, $2, $3, $4, $5)
ON CONFLICT (time) DO UPDATE SET
    wind_actual_mw   = EXCLUDED.wind_actual_mw,
    load_forecast_mw = EXCLUDED.load_forecast_mw,
    load_actual_mw   = EXCLUDED.load_actual_mw,
    solar_actual_mw  = EXCLUDED.solar_actual_mw
"""


async def insert_rows(conn: asyncpg.Connection, data: dict[datetime, tuple]) -> int:
    total = 0
    batch: list[tuple] = []

    for t, (wind, load_f, load_a, solar) in sorted(data.items()):
        batch.append((t, wind, load_f, load_a, solar))

        if len(batch) >= INSERT_BATCH:
            await conn.executemany(UPSERT_SQL, batch)
            total += len(batch)
            log.info("  Inserted %d rows (cumulative: %d)", len(batch), total)
            batch = []

    if batch:
        await conn.executemany(UPSERT_SQL, batch)
        total += len(batch)

    return total


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

async def main() -> None:
    if not GRIDSTATUS_KEY:
        raise RuntimeError("GRIDSTATUS_API_KEY not set")

    log.info("Connecting to %s@%s:%s/%s", PG_USER, PG_HOST, PG_PORT, PG_DB)
    conn = await asyncpg.connect(
        host=PG_HOST, port=PG_PORT, database=PG_DB,
        user=PG_USER, password=PG_PASS,
    )

    async with httpx.AsyncClient(
        headers={"x-api-key": GRIDSTATUS_KEY},
        follow_redirects=True,
    ) as client:
        # Pass 1: oldest-first (covers 2017 → ~2022-09)
        rows_asc  = await fetch_pass(client, "asc")
        # Pass 2: newest-first (covers ~2020-09 → present)
        rows_desc = await fetch_pass(client, "desc")

    # Merge, dedup by timestamp (desc overwrites asc for overlapping period)
    data: dict[datetime, tuple] = {}
    data.update(parse_rows(rows_asc))
    data.update(parse_rows(rows_desc))

    log.info("Unique in-range timestamps after merge: %d", len(data))
    if data:
        times = sorted(data.keys())
        log.info("Coverage: %s → %s", times[0], times[-1])

    total = await insert_rows(conn, data)
    log.info("=== Done. Total rows upserted: %d ===", total)

    await conn.close()


if __name__ == "__main__":
    asyncio.run(main())
