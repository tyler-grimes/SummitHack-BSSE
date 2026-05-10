"""Tests for ERCOT timestamp conversion logic (_spp_to_dict and _dam_to_dict).

These functions convert ERCOT's delivery_date + delivery_hour + delivery_interval
into ISO 8601 UTC timestamps.

ERCOT conventions:
- delivery_hour: 1-24 (hour 1 = 00:xx, hour 24 = 23:xx)
- delivery_interval: 1-4 (interval 1 = :00, 2 = :15, 3 = :30, 4 = :45)
"""


from src.fetchers.ercot import _dam_to_dict, _spp_to_dict
from src.models import ErcotDamRecord, ErcotSppRecord


def _make_spp(
    delivery_date: str = "2024-01-15",
    delivery_hour: int = 3,
    delivery_interval: int = 1,
    price: float = 42.0,
    node: str = "HB_NORTH",
) -> ErcotSppRecord:
    return ErcotSppRecord.model_validate(
        {
            "deliveryDate": delivery_date,
            "deliveryHour": delivery_hour,
            "deliveryInterval": delivery_interval,
            "settlementPoint": node,
            "settlementPointType": "HU",
            "settlementPointPrice": price,
        }
    )


def _make_dam(
    delivery_date: str = "2024-01-15",
    delivery_hour: int = 3,
    price: float = 42.0,
    node: str = "HB_NORTH",
) -> ErcotDamRecord:
    return ErcotDamRecord.model_validate(
        {
            "deliveryDate": delivery_date,
            "deliveryHour": delivery_hour,
            "settlementPoint": node,
            "settlementPointType": "HU",
            "settlementPointPrice": price,
        }
    )


# ── _spp_to_dict ──────────────────────────────────────────────────────────────

class TestSppToDict:
    def test_hour1_interval1_is_midnight(self):
        """hour=1, interval=1 → T00:00:00 (midnight)."""
        r = _make_spp(delivery_date="2024-01-15", delivery_hour=1, delivery_interval=1)
        result = _spp_to_dict(r, "ERCOT")
        assert result["timestamp"] == "2024-01-15T00:00:00+00:00", (
            "hour=1/interval=1 should produce midnight (T00:00:00)"
        )

    def test_hour1_interval2_is_15min(self):
        """hour=1, interval=2 → T00:15:00."""
        r = _make_spp(delivery_hour=1, delivery_interval=2)
        result = _spp_to_dict(r, "ERCOT")
        assert result["timestamp"] == "2024-01-15T00:15:00+00:00"

    def test_hour1_interval3_is_30min(self):
        r = _make_spp(delivery_hour=1, delivery_interval=3)
        result = _spp_to_dict(r, "ERCOT")
        assert result["timestamp"] == "2024-01-15T00:30:00+00:00"

    def test_hour1_interval4_is_45min(self):
        r = _make_spp(delivery_hour=1, delivery_interval=4)
        result = _spp_to_dict(r, "ERCOT")
        assert result["timestamp"] == "2024-01-15T00:45:00+00:00"

    def test_hour2_interval1(self):
        """hour=2, interval=1 → T01:00:00."""
        r = _make_spp(delivery_hour=2, delivery_interval=1)
        result = _spp_to_dict(r, "ERCOT")
        assert result["timestamp"] == "2024-01-15T01:00:00+00:00"

    def test_hour24_interval1(self):
        """hour=24, interval=1 → T23:00:00 (last hour of day)."""
        r = _make_spp(delivery_hour=24, delivery_interval=1)
        result = _spp_to_dict(r, "ERCOT")
        assert result["timestamp"] == "2024-01-15T23:00:00+00:00", (
            "hour=24 should map to 23:xx, not overflow past the day"
        )

    def test_hour24_interval4_is_last_interval(self):
        """hour=24, interval=4 → T23:45:00 (last 15-min slot of day)."""
        r = _make_spp(delivery_hour=24, delivery_interval=4)
        result = _spp_to_dict(r, "ERCOT")
        assert result["timestamp"] == "2024-01-15T23:45:00+00:00", (
            "hour=24/interval=4 should be last slot T23:45, not wrap to next day"
        )

    def test_timestamp_has_utc_offset(self):
        r = _make_spp(delivery_hour=6, delivery_interval=1)
        result = _spp_to_dict(r, "ERCOT")
        assert result["timestamp"].endswith("+00:00"), "Timestamp must carry UTC offset"

    def test_iso_key_set_correctly(self):
        r = _make_spp()
        result = _spp_to_dict(r, "ERCOT")
        assert result["iso"] == "ERCOT"

    def test_node_field(self):
        r = _make_spp(node="HB_SOUTH")
        result = _spp_to_dict(r, "ERCOT")
        assert result["node"] == "HB_SOUTH"

    def test_price_fields_populated(self):
        r = _make_spp(price=99.99)
        result = _spp_to_dict(r, "ERCOT")
        assert result["lmp"] == 99.99
        assert result["energy"] == 99.99

    def test_congestion_and_loss_are_zero(self):
        """ERCOT SPP does not decompose LMP components — congestion/loss default to 0."""
        r = _make_spp(price=50.0)
        result = _spp_to_dict(r, "ERCOT")
        assert result["congestion"] == 0.0
        assert result["loss"] == 0.0

    def test_zero_price(self):
        r = _make_spp(price=0.0)
        result = _spp_to_dict(r, "ERCOT")
        assert result["lmp"] == 0.0

    def test_negative_price(self):
        r = _make_spp(price=-25.5)
        result = _spp_to_dict(r, "ERCOT")
        assert result["lmp"] == -25.5

    def test_result_keys_complete(self):
        r = _make_spp()
        result = _spp_to_dict(r, "ERCOT")
        assert set(result.keys()) == {"timestamp", "iso", "node", "lmp", "energy", "congestion", "loss"}


# ── _dam_to_dict ──────────────────────────────────────────────────────────────

class TestDamToDict:
    def test_hour1_is_midnight(self):
        """DAM: hour=1 → T00:00:00."""
        r = _make_dam(delivery_date="2024-01-15", delivery_hour=1)
        result = _dam_to_dict(r, "ERCOT")
        assert result["timestamp"] == "2024-01-15T00:00:00+00:00", (
            "DAM hour=1 should produce midnight"
        )

    def test_hour24_is_last_hour(self):
        """DAM: hour=24 → T23:00:00."""
        r = _make_dam(delivery_date="2024-01-15", delivery_hour=24)
        result = _dam_to_dict(r, "ERCOT")
        assert result["timestamp"] == "2024-01-15T23:00:00+00:00", (
            "DAM hour=24 should be T23:00, not overflow to next day"
        )

    def test_hour12_midday(self):
        r = _make_dam(delivery_hour=12)
        result = _dam_to_dict(r, "ERCOT")
        assert result["timestamp"] == "2024-01-15T11:00:00+00:00"

    def test_timestamp_has_utc_offset(self):
        r = _make_dam(delivery_hour=3)
        result = _dam_to_dict(r, "ERCOT")
        assert result["timestamp"].endswith("+00:00")

    def test_zero_price_included(self):
        r = _make_dam(price=0.0)
        result = _dam_to_dict(r, "ERCOT")
        assert result["lmp"] == 0.0

    def test_negative_price(self):
        r = _make_dam(price=-10.0)
        result = _dam_to_dict(r, "ERCOT")
        assert result["lmp"] == -10.0

    def test_result_keys_complete(self):
        r = _make_dam()
        result = _dam_to_dict(r, "ERCOT")
        assert set(result.keys()) == {"timestamp", "iso", "node", "lmp", "energy", "congestion", "loss"}

    def test_minutes_always_zero(self):
        """DAM uses hourly resolution — minutes must always be :00."""
        for hour in [1, 12, 24]:
            r = _make_dam(delivery_hour=hour)
            result = _dam_to_dict(r, "ERCOT")
            ts = result["timestamp"]
            # e.g. "2024-01-15T11:00:00+00:00" → split on T, take time part
            time_part = ts.split("T")[1]
            assert time_part.startswith(f"{(hour - 1):02d}:00"), (
                f"DAM hour={hour} should have :00 minutes, got {time_part}"
            )
