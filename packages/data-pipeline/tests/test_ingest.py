"""Tests for the ingest worker — both ISOs run, DB inserts called, Kafka published.

All external I/O (fetchers, DB, Kafka) is mocked.
"""

from datetime import date
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from src.ingest import (
    ERCOT_ANCILLARY_SERVICES,
    ERCOT_DEFAULT_NODES,
    PJM_ANCILLARY_SERVICES,
    PJM_DEFAULT_NODES,
    _publish,
    ingest_ercot,
    ingest_pjm,
    run_daily_ingest,
)

# ── Helpers ───────────────────────────────────────────────────────────────────

def _mock_producer() -> MagicMock:
    producer = MagicMock()
    producer.send = MagicMock()
    producer.flush = MagicMock()
    producer.close = MagicMock()
    return producer


def _mock_ercot_fetcher(rt_records=None, da_records=None, as_records=None):
    """Return a mock ErcotFetcher context manager."""
    fetcher = AsyncMock()
    fetcher.fetch_rt_lmp = AsyncMock(return_value=rt_records or [])
    fetcher.fetch_da_lmp = AsyncMock(return_value=da_records or [])
    fetcher.fetch_ancillary_prices = AsyncMock(return_value=as_records or [])

    cm = AsyncMock()
    cm.__aenter__ = AsyncMock(return_value=fetcher)
    cm.__aexit__ = AsyncMock(return_value=False)
    return cm, fetcher


def _mock_pjm_fetcher(rt_records=None, da_records=None, as_records=None):
    fetcher = AsyncMock()
    fetcher.fetch_rt_lmp = AsyncMock(return_value=rt_records or [])
    fetcher.fetch_da_lmp = AsyncMock(return_value=da_records or [])
    fetcher.fetch_ancillary_prices = AsyncMock(return_value=as_records or [])

    cm = AsyncMock()
    cm.__aenter__ = AsyncMock(return_value=fetcher)
    cm.__aexit__ = AsyncMock(return_value=False)
    return cm, fetcher


def _lmp_record(iso: str = "ERCOT") -> dict:
    return {
        "timestamp": "2024-01-15T00:00:00+00:00",
        "iso": iso,
        "node": "HB_NORTH",
        "lmp": 42.50,
        "energy": 42.50,
        "congestion": 0.0,
        "loss": 0.0,
    }


# ── _publish ──────────────────────────────────────────────────────────────────

class TestPublish:
    def test_publish_encodes_key_as_bytes(self):
        producer = _mock_producer()
        _publish(producer, "market.prices", "ERCOT.RT_LMP", {"count": 5})

        producer.send.assert_called_once()
        call_kwargs = producer.send.call_args
        # key should be bytes
        assert call_kwargs[1]["key"] == b"ERCOT.RT_LMP", (
            "Key must be encoded to bytes before sending to Kafka"
        )

    def test_publish_sends_to_correct_topic(self):
        producer = _mock_producer()
        _publish(producer, "market.prices", "key", {"data": "x"})

        assert producer.send.call_args[0][0] == "market.prices"

    def test_publish_sends_payload_as_value(self):
        producer = _mock_producer()
        payload = {"count": 10, "date": "2024-01-15"}
        _publish(producer, "topic", "key", payload)

        assert producer.send.call_args[1]["value"] == payload


# ── ingest_ercot ──────────────────────────────────────────────────────────────

class TestIngestErcot:
    async def test_fetches_rt_lmp_for_default_nodes(self):
        cm, fetcher = _mock_ercot_fetcher()
        producer = _mock_producer()
        start = date(2024, 1, 15)

        with patch("src.ingest.ErcotFetcher", return_value=cm), \
             patch("src.ingest.insert_lmp_batch", AsyncMock(return_value=0)), \
             patch("src.ingest.insert_ancillary_batch", AsyncMock(return_value=0)):
            await ingest_ercot(start, start, producer)

        fetcher.fetch_rt_lmp.assert_called_once_with(ERCOT_DEFAULT_NODES, start, start)

    async def test_fetches_da_lmp_for_default_nodes(self):
        cm, fetcher = _mock_ercot_fetcher()
        producer = _mock_producer()
        start = date(2024, 1, 15)

        with patch("src.ingest.ErcotFetcher", return_value=cm), \
             patch("src.ingest.insert_lmp_batch", AsyncMock(return_value=0)), \
             patch("src.ingest.insert_ancillary_batch", AsyncMock(return_value=0)):
            await ingest_ercot(start, start, producer)

        fetcher.fetch_da_lmp.assert_called_once_with(ERCOT_DEFAULT_NODES, start, start)

    async def test_fetches_ancillary_prices(self):
        cm, fetcher = _mock_ercot_fetcher()
        producer = _mock_producer()
        start = date(2024, 1, 15)

        with patch("src.ingest.ErcotFetcher", return_value=cm), \
             patch("src.ingest.insert_lmp_batch", AsyncMock(return_value=0)), \
             patch("src.ingest.insert_ancillary_batch", AsyncMock(return_value=0)):
            await ingest_ercot(start, start, producer)

        fetcher.fetch_ancillary_prices.assert_called_once_with(ERCOT_ANCILLARY_SERVICES, start, start)

    async def test_insert_lmp_batch_called_twice(self):
        """insert_lmp_batch called once for RT and once for DA."""
        cm, _ = _mock_ercot_fetcher()
        producer = _mock_producer()
        start = date(2024, 1, 15)
        insert_lmp_mock = AsyncMock(return_value=0)

        with patch("src.ingest.ErcotFetcher", return_value=cm), \
             patch("src.ingest.insert_lmp_batch", insert_lmp_mock), \
             patch("src.ingest.insert_ancillary_batch", AsyncMock(return_value=0)):
            await ingest_ercot(start, start, producer)

        assert insert_lmp_mock.call_count == 2, (
            "insert_lmp_batch must be called once for RT and once for DA"
        )

    async def test_kafka_published_for_rt_lmp(self):
        """Kafka publish called after RT LMP insert with correct topic and key."""
        rt_records = [_lmp_record("ERCOT")]
        cm, _ = _mock_ercot_fetcher(rt_records=rt_records)
        producer = _mock_producer()
        start = date(2024, 1, 15)

        with patch("src.ingest.ErcotFetcher", return_value=cm), \
             patch("src.ingest.insert_lmp_batch", AsyncMock(return_value=1)), \
             patch("src.ingest.insert_ancillary_batch", AsyncMock(return_value=0)):
            await ingest_ercot(start, start, producer)

        producer.send.assert_called_once()
        call_args = producer.send.call_args
        assert call_args[0][0] == "market.prices", "Topic must be 'market.prices'"
        assert call_args[1]["key"] == b"ERCOT.RT_LMP", "Key must be ERCOT.RT_LMP"

    async def test_kafka_not_published_for_da_lmp(self):
        """Only RT LMP triggers a Kafka publish — DA LMP does not."""
        cm, _ = _mock_ercot_fetcher(da_records=[_lmp_record("ERCOT")])
        producer = _mock_producer()
        start = date(2024, 1, 15)

        with patch("src.ingest.ErcotFetcher", return_value=cm), \
             patch("src.ingest.insert_lmp_batch", AsyncMock(return_value=1)), \
             patch("src.ingest.insert_ancillary_batch", AsyncMock(return_value=0)):
            await ingest_ercot(start, start, producer)

        # Only 1 Kafka message (for RT), not 2
        assert producer.send.call_count == 1, (
            "DA LMP should NOT trigger a Kafka publish — only RT LMP does"
        )


# ── ingest_pjm ────────────────────────────────────────────────────────────────

class TestIngestPjm:
    async def test_fetches_rt_lmp_for_default_nodes(self):
        cm, fetcher = _mock_pjm_fetcher()
        producer = _mock_producer()
        start = date(2024, 1, 15)

        with patch("src.ingest.PjmFetcher", return_value=cm), \
             patch("src.ingest.insert_lmp_batch", AsyncMock(return_value=0)), \
             patch("src.ingest.insert_ancillary_batch", AsyncMock(return_value=0)):
            await ingest_pjm(start, start, producer)

        fetcher.fetch_rt_lmp.assert_called_once_with(PJM_DEFAULT_NODES, start, start)

    async def test_fetches_ancillary_prices(self):
        cm, fetcher = _mock_pjm_fetcher()
        producer = _mock_producer()
        start = date(2024, 1, 15)

        with patch("src.ingest.PjmFetcher", return_value=cm), \
             patch("src.ingest.insert_lmp_batch", AsyncMock(return_value=0)), \
             patch("src.ingest.insert_ancillary_batch", AsyncMock(return_value=0)):
            await ingest_pjm(start, start, producer)

        fetcher.fetch_ancillary_prices.assert_called_once_with(PJM_ANCILLARY_SERVICES, start, start)

    async def test_kafka_published_for_rt_lmp(self):
        rt_records = [_lmp_record("PJM")]
        cm, _ = _mock_pjm_fetcher(rt_records=rt_records)
        producer = _mock_producer()
        start = date(2024, 1, 15)

        with patch("src.ingest.PjmFetcher", return_value=cm), \
             patch("src.ingest.insert_lmp_batch", AsyncMock(return_value=1)), \
             patch("src.ingest.insert_ancillary_batch", AsyncMock(return_value=0)):
            await ingest_pjm(start, start, producer)

        call_args = producer.send.call_args
        assert call_args[0][0] == "market.prices"
        assert call_args[1]["key"] == b"PJM.RT_LMP"

    async def test_insert_lmp_batch_called_twice(self):
        cm, _ = _mock_pjm_fetcher()
        producer = _mock_producer()
        start = date(2024, 1, 15)
        insert_lmp_mock = AsyncMock(return_value=0)

        with patch("src.ingest.PjmFetcher", return_value=cm), \
             patch("src.ingest.insert_lmp_batch", insert_lmp_mock), \
             patch("src.ingest.insert_ancillary_batch", AsyncMock(return_value=0)):
            await ingest_pjm(start, start, producer)

        assert insert_lmp_mock.call_count == 2


# ── run_daily_ingest ──────────────────────────────────────────────────────────

class TestRunDailyIngest:
    async def test_both_isos_run(self):
        """Both ingest_ercot and ingest_pjm must be called."""
        ercot_mock = AsyncMock()
        pjm_mock = AsyncMock()
        producer = _mock_producer()

        with patch("src.ingest.init_pool", AsyncMock()), \
             patch("src.ingest.close_pool", AsyncMock()), \
             patch("src.ingest._kafka_producer", return_value=producer), \
             patch("src.ingest.ingest_ercot", ercot_mock), \
             patch("src.ingest.ingest_pjm", pjm_mock):
            await run_daily_ingest(date(2024, 1, 15))

        ercot_mock.assert_called_once(), "ingest_ercot must be called"
        pjm_mock.assert_called_once(), "ingest_pjm must be called"

    async def test_both_isos_receive_same_date(self):
        ercot_mock = AsyncMock()
        pjm_mock = AsyncMock()
        producer = _mock_producer()
        target = date(2024, 3, 20)

        with patch("src.ingest.init_pool", AsyncMock()), \
             patch("src.ingest.close_pool", AsyncMock()), \
             patch("src.ingest._kafka_producer", return_value=producer), \
             patch("src.ingest.ingest_ercot", ercot_mock), \
             patch("src.ingest.ingest_pjm", pjm_mock):
            await run_daily_ingest(target)

        ercot_args = ercot_mock.call_args[0]
        pjm_args = pjm_mock.call_args[0]
        assert ercot_args[0] == target
        assert pjm_args[0] == target

    async def test_producer_flushed_after_ingest(self):
        """producer.flush() must be called after both ISOs complete."""
        producer = _mock_producer()

        with patch("src.ingest.init_pool", AsyncMock()), \
             patch("src.ingest.close_pool", AsyncMock()), \
             patch("src.ingest._kafka_producer", return_value=producer), \
             patch("src.ingest.ingest_ercot", AsyncMock()), \
             patch("src.ingest.ingest_pjm", AsyncMock()):
            await run_daily_ingest(date(2024, 1, 15))

        producer.flush.assert_called_once(), "producer.flush() must be called"

    async def test_producer_closed_in_finally(self):
        """producer.close() must be called even if an ISO raises."""
        producer = _mock_producer()

        with patch("src.ingest.init_pool", AsyncMock()), \
             patch("src.ingest.close_pool", AsyncMock()), \
             patch("src.ingest._kafka_producer", return_value=producer), \
             patch("src.ingest.ingest_ercot", AsyncMock(side_effect=RuntimeError("network error"))), \
             patch("src.ingest.ingest_pjm", AsyncMock()):
            with pytest.raises(RuntimeError):
                await run_daily_ingest(date(2024, 1, 15))

        producer.close.assert_called_once(), (
            "producer.close() must be called in finally block even on error"
        )

    async def test_pool_closed_in_finally(self):
        """close_pool() must be called in the finally block."""
        producer = _mock_producer()
        close_pool_mock = AsyncMock()

        with patch("src.ingest.init_pool", AsyncMock()), \
             patch("src.ingest.close_pool", close_pool_mock), \
             patch("src.ingest._kafka_producer", return_value=producer), \
             patch("src.ingest.ingest_ercot", AsyncMock(side_effect=RuntimeError("fail"))), \
             patch("src.ingest.ingest_pjm", AsyncMock()):
            with pytest.raises(RuntimeError):
                await run_daily_ingest(date(2024, 1, 15))

        close_pool_mock.assert_called_once(), (
            "close_pool() must be called in finally block even on error"
        )

    async def test_default_date_is_yesterday(self):
        """When no target_date provided, should default to yesterday."""
        from datetime import timedelta


        producer = _mock_producer()
        ercot_mock = AsyncMock()
        pjm_mock = AsyncMock()

        with patch("src.ingest.init_pool", AsyncMock()), \
             patch("src.ingest.close_pool", AsyncMock()), \
             patch("src.ingest._kafka_producer", return_value=producer), \
             patch("src.ingest.ingest_ercot", ercot_mock), \
             patch("src.ingest.ingest_pjm", pjm_mock):
            await run_daily_ingest()  # no date passed

        ercot_args = ercot_mock.call_args[0]
        # The date should be recent (within 2 days of "today" to avoid flakiness)
        from datetime import date as date_cls
        today = date_cls.today()
        yesterday = today - timedelta(days=1)
        assert ercot_args[0] == yesterday, (
            f"Default date should be yesterday ({yesterday}), got {ercot_args[0]}"
        )
