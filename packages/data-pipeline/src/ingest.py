"""
Main ingestion worker. Fetches LMP + ancillary data from ERCOT and PJM via
GridStatus.io, writes to TimescaleDB, publishes events to Kafka.
"""

import asyncio
import json
import logging
from datetime import date, timedelta
from typing import Any

from kafka import KafkaProducer

from .config import config
from .db import close_pool, init_pool, insert_ancillary_batch, insert_lmp_batch, insert_outage_batch
from .fetchers.gridstatus import GridStatusFetcher

logger = logging.getLogger(__name__)

ERCOT_DEFAULT_NODES = ["HB_NORTH", "HB_SOUTH", "HB_WEST", "HB_HOUSTON"]
PJM_DEFAULT_NODES = ["AEP GEN HUB", "DOM HUB", "NI HUB", "PJMZN_AEP"]

# Canonical service keys — must match GridStatusFetcher._ERCOT_AS_COL_MAP values
ERCOT_ANCILLARY_SERVICES = ["REG_UP", "REG_DOWN", "NONSPIN", "SPIN"]
# PJM ancillary not available via GridStatus — empty list, fetcher returns []
PJM_ANCILLARY_SERVICES: list[str] = []


def _kafka_producer() -> KafkaProducer:
    return KafkaProducer(
        bootstrap_servers=config.kafka_bootstrap_servers,
        value_serializer=lambda v: json.dumps(v).encode(),
        acks="all",
    )


def _publish(producer: KafkaProducer, topic: str, key: str, payload: dict[str, Any]) -> None:
    producer.send(topic, key=key.encode(), value=payload)


async def ingest_ercot(start: date, end: date, producer: KafkaProducer) -> None:
    async with GridStatusFetcher("ERCOT") as fetcher:
        logger.info("ERCOT: fetching RT LMP %s → %s", start, end)
        rt_records = await fetcher.fetch_rt_lmp(ERCOT_DEFAULT_NODES, start, end)
        inserted = await insert_lmp_batch(rt_records)
        logger.info("ERCOT RT LMP: inserted %d records", inserted)
        _publish(producer, "market.prices", "ERCOT.RT_LMP", {"count": inserted, "date": str(start)})

        logger.info("ERCOT: fetching DA LMP %s → %s", start, end)
        da_records = await fetcher.fetch_da_lmp(ERCOT_DEFAULT_NODES, start, end)
        inserted = await insert_lmp_batch(da_records)
        logger.info("ERCOT DA LMP: inserted %d records", inserted)

        logger.info("ERCOT: fetching ancillary prices")
        as_records = await fetcher.fetch_ancillary_prices(ERCOT_ANCILLARY_SERVICES, start, end)
        inserted = await insert_ancillary_batch(as_records)
        logger.info("ERCOT ancillary: inserted %d records", inserted)

        logger.info("ERCOT: fetching outage capacity")
        outage_records = await fetcher.fetch_outage_capacity(start, end)
        inserted = await insert_outage_batch(outage_records)
        logger.info("ERCOT outage capacity: inserted %d records", inserted)


async def ingest_pjm(start: date, end: date, producer: KafkaProducer) -> None:
    async with GridStatusFetcher("PJM") as fetcher:
        logger.info("PJM: fetching RT LMP %s → %s", start, end)
        rt_records = await fetcher.fetch_rt_lmp(PJM_DEFAULT_NODES, start, end)
        inserted = await insert_lmp_batch(rt_records)
        logger.info("PJM RT LMP: inserted %d records", inserted)
        _publish(producer, "market.prices", "PJM.RT_LMP", {"count": inserted, "date": str(start)})

        logger.info("PJM: fetching DA LMP %s → %s", start, end)
        da_records = await fetcher.fetch_da_lmp(PJM_DEFAULT_NODES, start, end)
        inserted = await insert_lmp_batch(da_records)
        logger.info("PJM DA LMP: inserted %d records", inserted)

        logger.info("PJM: fetching ancillary prices (unsupported via GridStatus — skipped)")
        as_records = await fetcher.fetch_ancillary_prices(PJM_ANCILLARY_SERVICES, start, end)
        inserted = await insert_ancillary_batch(as_records)
        logger.info("PJM ancillary: inserted %d records", inserted)


async def run_daily_ingest(target_date: date | None = None) -> None:
    """Ingest one day of data from both ISOs."""
    day = target_date or date.today() - timedelta(days=1)
    await init_pool()
    producer = _kafka_producer()

    try:
        await asyncio.gather(
            ingest_ercot(day, day, producer),
            ingest_pjm(day, day, producer),
        )
        producer.flush()
        logger.info("Daily ingest complete for %s", day)
    finally:
        producer.close()
        await close_pool()


if __name__ == "__main__":
    import sys
    logging.basicConfig(level=logging.INFO)
    target = date.fromisoformat(sys.argv[1]) if len(sys.argv) > 1 else None
    asyncio.run(run_daily_ingest(target))
