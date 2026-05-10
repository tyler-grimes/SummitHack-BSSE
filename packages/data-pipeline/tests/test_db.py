"""Tests for the DB layer — insert_lmp_batch and insert_ancillary_batch.

All asyncpg I/O is mocked; no real DB connection is made.
"""

from unittest.mock import AsyncMock, MagicMock

import pytest
import src.db as db_module
from src.db import insert_ancillary_batch, insert_lmp_batch

# ── Helpers ───────────────────────────────────────────────────────────────────

def _make_mock_pool(conn: AsyncMock) -> MagicMock:
    """Build a mock asyncpg pool whose .acquire() yields *conn*."""
    pool = MagicMock()
    # pool.acquire() is an async context manager
    acquire_cm = MagicMock()
    acquire_cm.__aenter__ = AsyncMock(return_value=conn)
    acquire_cm.__aexit__ = AsyncMock(return_value=False)
    pool.acquire = MagicMock(return_value=acquire_cm)
    return pool


def _make_mock_conn() -> AsyncMock:
    conn = AsyncMock()
    conn.executemany = AsyncMock()
    return conn


def _lmp_record(**overrides) -> dict:
    base = {
        "timestamp": "2024-01-15T00:00:00+00:00",
        "iso": "ERCOT",
        "node": "HB_NORTH",
        "lmp": 42.50,
        "energy": 42.50,
        "congestion": 0.0,
        "loss": 0.0,
    }
    base.update(overrides)
    return base


def _ancillary_record(**overrides) -> dict:
    base = {
        "timestamp": "2024-01-15T00:00:00+00:00",
        "iso": "ERCOT",
        "service": "Reg-Up",
        "clearing_price": 5.75,
        "mileage": None,
    }
    base.update(overrides)
    return base


# ── insert_lmp_batch ──────────────────────────────────────────────────────────

class TestInsertLmpBatch:
    async def test_empty_list_returns_zero_without_db_call(self):
        """Empty list must short-circuit and return 0 without touching the DB."""
        conn = _make_mock_conn()
        pool = _make_mock_pool(conn)
        db_module._pool = pool

        result = await insert_lmp_batch([])

        assert result == 0, "Empty list should return 0"
        conn.executemany.assert_not_called(), "executemany must not be called for empty list"

    async def test_single_record_inserts_and_returns_count(self):
        conn = _make_mock_conn()
        pool = _make_mock_pool(conn)
        db_module._pool = pool

        records = [_lmp_record()]
        result = await insert_lmp_batch(records)

        assert result == 1, "Should return count of records passed in"
        conn.executemany.assert_called_once(), "executemany must be called exactly once"

    async def test_multiple_records_returns_correct_count(self):
        conn = _make_mock_conn()
        pool = _make_mock_pool(conn)
        db_module._pool = pool

        records = [_lmp_record(node=f"NODE_{i}") for i in range(5)]
        result = await insert_lmp_batch(records)

        assert result == 5, "Should return 5 for 5 records"

    async def test_correct_column_order_in_executemany(self):
        """executemany receives tuples in the order (timestamp, iso, node, lmp, energy, congestion, loss)."""
        conn = _make_mock_conn()
        pool = _make_mock_pool(conn)
        db_module._pool = pool

        record = _lmp_record(
            timestamp="2024-01-15T03:00:00+00:00",
            iso="PJM",
            node="DOM HUB",
            lmp=38.50,
            energy=36.00,
            congestion=2.00,
            loss=0.50,
        )
        await insert_lmp_batch([record])

        call_args = conn.executemany.call_args
        rows = call_args[0][1]  # second positional arg is the iterable of rows
        assert len(rows) == 1
        ts, iso, node, lmp, energy, congestion, loss = rows[0]
        from datetime import datetime, timezone
        assert ts == datetime(2024, 1, 15, 3, 0, 0, tzinfo=timezone.utc)
        assert iso == "PJM"
        assert node == "DOM HUB"
        assert lmp == 38.50
        assert energy == 36.00
        assert congestion == 2.00
        assert loss == 0.50

    async def test_missing_optional_fields_default_to_zero(self):
        """energy/congestion/loss are optional — absent keys default to 0.0."""
        conn = _make_mock_conn()
        pool = _make_mock_pool(conn)
        db_module._pool = pool

        # Intentionally omit optional fields
        record = {
            "timestamp": "2024-01-15T00:00:00+00:00",
            "iso": "ERCOT",
            "node": "HB_WEST",
            "lmp": 30.0,
        }
        await insert_lmp_batch([record])

        rows = conn.executemany.call_args[0][1]
        _, _, _, _, energy, congestion, loss = rows[0]
        assert energy == 0.0, "Missing energy should default to 0.0"
        assert congestion == 0.0, "Missing congestion should default to 0.0"
        assert loss == 0.0, "Missing loss should default to 0.0"

    async def test_zero_price_record_inserted(self):
        """A record with lmp=0.0 must not be silently skipped."""
        conn = _make_mock_conn()
        pool = _make_mock_pool(conn)
        db_module._pool = pool

        result = await insert_lmp_batch([_lmp_record(lmp=0.0)])

        assert result == 1, "Zero-price record must be inserted"

    async def test_negative_price_record_inserted(self):
        """Negative prices are valid in electricity markets."""
        conn = _make_mock_conn()
        pool = _make_mock_pool(conn)
        db_module._pool = pool

        result = await insert_lmp_batch([_lmp_record(lmp=-50.0)])

        assert result == 1, "Negative-price record must be inserted"

    async def test_raises_if_pool_not_initialized(self):
        """acquire() raises RuntimeError when _pool is None."""
        db_module._pool = None

        with pytest.raises(RuntimeError, match="init_pool"):
            await insert_lmp_batch([_lmp_record()])

    async def test_sql_contains_on_conflict_do_nothing(self):
        """INSERT statement must include ON CONFLICT DO NOTHING for idempotency."""
        conn = _make_mock_conn()
        pool = _make_mock_pool(conn)
        db_module._pool = pool

        await insert_lmp_batch([_lmp_record()])

        sql = conn.executemany.call_args[0][0]
        assert "ON CONFLICT DO NOTHING" in sql, (
            "LMP insert must be idempotent via ON CONFLICT DO NOTHING"
        )


# ── insert_ancillary_batch ────────────────────────────────────────────────────

class TestInsertAncillaryBatch:
    async def test_empty_list_returns_zero_without_db_call(self):
        conn = _make_mock_conn()
        pool = _make_mock_pool(conn)
        db_module._pool = pool

        result = await insert_ancillary_batch([])

        assert result == 0, "Empty list should return 0"
        conn.executemany.assert_not_called(), "executemany must not be called for empty list"

    async def test_single_record_inserts_and_returns_count(self):
        conn = _make_mock_conn()
        pool = _make_mock_pool(conn)
        db_module._pool = pool

        result = await insert_ancillary_batch([_ancillary_record()])

        assert result == 1, "Single record should return 1"
        conn.executemany.assert_called_once()

    async def test_multiple_records_correct_count(self):
        conn = _make_mock_conn()
        pool = _make_mock_pool(conn)
        db_module._pool = pool

        records = [_ancillary_record(service=f"SVC_{i}") for i in range(4)]
        result = await insert_ancillary_batch(records)

        assert result == 4

    async def test_correct_column_order(self):
        """Rows must be (timestamp, iso, service, clearing_price, mileage)."""
        conn = _make_mock_conn()
        pool = _make_mock_pool(conn)
        db_module._pool = pool

        record = _ancillary_record(
            timestamp="2024-01-15T06:00:00+00:00",
            iso="PJM",
            service="REG",
            clearing_price=12.5,
            mileage=0.25,
        )
        await insert_ancillary_batch([record])

        rows = conn.executemany.call_args[0][1]
        ts, iso, service, clearing_price, mileage = rows[0]
        from datetime import datetime, timezone
        assert ts == datetime(2024, 1, 15, 6, 0, 0, tzinfo=timezone.utc)
        assert iso == "PJM"
        assert service == "REG"
        assert clearing_price == 12.5
        assert mileage == 0.25

    async def test_mileage_can_be_none(self):
        """mileage is optional and may be None."""
        conn = _make_mock_conn()
        pool = _make_mock_pool(conn)
        db_module._pool = pool

        await insert_ancillary_batch([_ancillary_record(mileage=None)])

        rows = conn.executemany.call_args[0][1]
        *_, mileage = rows[0]
        assert mileage is None, "mileage=None must be passed through as NULL"

    async def test_raises_if_pool_not_initialized(self):
        db_module._pool = None

        with pytest.raises(RuntimeError, match="init_pool"):
            await insert_ancillary_batch([_ancillary_record()])

    async def test_sql_contains_on_conflict_do_nothing(self):
        conn = _make_mock_conn()
        pool = _make_mock_pool(conn)
        db_module._pool = pool

        await insert_ancillary_batch([_ancillary_record()])

        sql = conn.executemany.call_args[0][0]
        assert "ON CONFLICT DO NOTHING" in sql, (
            "Ancillary insert must be idempotent via ON CONFLICT DO NOTHING"
        )
