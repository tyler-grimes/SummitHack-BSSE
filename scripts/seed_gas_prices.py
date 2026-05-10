"""
Seed Henry Hub natural gas spot prices from EIA into the gas_prices table.

Source: EIA API v2 series NG.RNGWHHD.D (Daily Henry Hub Natural Gas Spot Price)
No API key required beyond DEMO_KEY — 5000 rows covers back to 2006.
Idempotent via ON CONFLICT DO NOTHING.

Usage:
    python scripts/seed_gas_prices.py
"""

import asyncio
import logging
import os
from datetime import date

import asyncpg
import httpx

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)

EIA_URL    = "https://api.eia.gov/v2/seriesid/NG.RNGWHHD.D"
EIA_KEY    = os.environ.get("EIA_API_KEY", "DEMO_KEY")

PG_HOST = os.environ.get("POSTGRES_HOST", "localhost")
PG_PORT = int(os.environ.get("POSTGRES_PORT", "5432"))
PG_DB   = os.environ.get("POSTGRES_DB", "energy_trading")
PG_USER = os.environ.get("POSTGRES_USER", "postgres")
PG_PASS = os.environ.get("POSTGRES_PASSWORD", "postgres_energy_password")

UPSERT_SQL = """
INSERT INTO gas_prices (date, henry_hub)
VALUES ($1, $2)
ON CONFLICT (date) DO NOTHING
"""


async def main() -> None:
    log.info("Fetching Henry Hub spot prices from EIA ...")
    async with httpx.AsyncClient() as client:
        resp = await client.get(EIA_URL, params={"api_key": EIA_KEY}, timeout=30)
        resp.raise_for_status()
        body = resp.json()

    rows = body.get("response", {}).get("data", [])
    log.info("EIA returned %d rows", len(rows))
    if not rows:
        raise RuntimeError("No data returned from EIA")

    log.info("Date range: %s → %s", rows[-1]["period"], rows[0]["period"])

    log.info("Connecting to %s@%s:%s/%s", PG_USER, PG_HOST, PG_PORT, PG_DB)
    conn = await asyncpg.connect(
        host=PG_HOST, port=PG_PORT, database=PG_DB,
        user=PG_USER, password=PG_PASS,
    )

    batch = []
    for r in rows:
        try:
            d = date.fromisoformat(r["period"])
            v = float(r["value"])
            batch.append((d, v))
        except (ValueError, TypeError, KeyError):
            continue

    await conn.executemany(UPSERT_SQL, batch)
    log.info("Inserted %d rows", len(batch))
    await conn.close()
    log.info("=== Done ===")


if __name__ == "__main__":
    asyncio.run(main())
