"""Tests for Pydantic models — validation, alias mapping, edge cases."""

import pytest
from pydantic import ValidationError
from src.models import (
    ErcotDamRecord,
    ErcotMeta,
    ErcotSppRecord,
    ErcotSppResponse,
    PjmAncillaryRecord,
    PjmDaLmpRecord,
    PjmPaginatedResponse,
    PjmRtLmpRecord,
)

# ── ErcotMeta ─────────────────────────────────────────────────────────────────

class TestErcotMeta:
    def test_valid_camelcase_aliases(self):
        m = ErcotMeta.model_validate(
            {"totalRecords": 100, "pageSize": 50, "totalPages": 2, "currentPage": 1}
        )
        assert m.total_records == 100, "total_records should map from totalRecords"
        assert m.page_size == 50, "page_size should map from pageSize"
        assert m.total_pages == 2, "total_pages should map from totalPages"
        assert m.current_page == 1, "current_page should map from currentPage"

    def test_missing_required_field_raises(self):
        with pytest.raises(ValidationError, match="totalRecords"):
            ErcotMeta.model_validate(
                {"pageSize": 50, "totalPages": 1, "currentPage": 1}
            )

    def test_wrong_type_raises(self):
        with pytest.raises(ValidationError):
            ErcotMeta.model_validate(
                {"totalRecords": "not-an-int", "pageSize": 50, "totalPages": 1, "currentPage": 1}
            )


# ── ErcotSppRecord ────────────────────────────────────────────────────────────

class TestErcotSppRecord:
    def _valid_payload(self, **overrides) -> dict:
        base = {
            "deliveryDate": "2024-01-15",
            "deliveryHour": 3,
            "deliveryInterval": 2,
            "settlementPoint": "HB_NORTH",
            "settlementPointType": "HU",
            "settlementPointPrice": 42.50,
        }
        base.update(overrides)
        return base

    def test_valid_record_maps_aliases(self):
        r = ErcotSppRecord.model_validate(self._valid_payload())
        assert r.delivery_date == "2024-01-15"
        assert r.delivery_hour == 3
        assert r.delivery_interval == 2
        assert r.settlement_point == "HB_NORTH"
        assert r.settlement_point_price == 42.50

    def test_dst_flag_optional_defaults_none(self):
        r = ErcotSppRecord.model_validate(self._valid_payload())
        assert r.dst_flag is None, "DSTFlag should default to None when absent"

    def test_dst_flag_provided(self):
        r = ErcotSppRecord.model_validate(self._valid_payload(DSTFlag="Y"))
        assert r.dst_flag == "Y"

    def test_zero_price_is_valid(self):
        r = ErcotSppRecord.model_validate(self._valid_payload(settlementPointPrice=0.0))
        assert r.settlement_point_price == 0.0, "Price of 0.0 must be accepted"

    def test_negative_price_is_valid(self):
        r = ErcotSppRecord.model_validate(self._valid_payload(settlementPointPrice=-15.75))
        assert r.settlement_point_price == -15.75, "Negative prices are valid in electricity markets"

    def test_missing_settlement_point_raises(self):
        payload = self._valid_payload()
        del payload["settlementPoint"]
        with pytest.raises(ValidationError):
            ErcotSppRecord.model_validate(payload)

    def test_wrong_price_type_raises(self):
        with pytest.raises(ValidationError):
            ErcotSppRecord.model_validate(self._valid_payload(settlementPointPrice="expensive"))


# ── ErcotSppResponse ──────────────────────────────────────────────────────────

class TestErcotSppResponse:
    def test_empty_data_array_is_valid(self):
        payload = {
            "_meta": {"totalRecords": 0, "pageSize": 100, "totalPages": 0, "currentPage": 1},
            "data": [],
        }
        resp = ErcotSppResponse.model_validate(payload)
        assert resp.data == [], "Empty data array should be valid"
        assert resp.meta.total_records == 0

    def test_meta_uses_underscore_alias(self):
        payload = {
            "_meta": {"totalRecords": 1, "pageSize": 1, "totalPages": 1, "currentPage": 1},
            "data": [
                {
                    "deliveryDate": "2024-01-15",
                    "deliveryHour": 1,
                    "deliveryInterval": 1,
                    "settlementPoint": "HB_NORTH",
                    "settlementPointType": "HU",
                    "settlementPointPrice": 30.0,
                }
            ],
        }
        resp = ErcotSppResponse.model_validate(payload)
        assert len(resp.data) == 1
        assert resp.meta.current_page == 1

    def test_missing_meta_raises(self):
        with pytest.raises(ValidationError):
            ErcotSppResponse.model_validate({"data": []})


# ── ErcotDamRecord ────────────────────────────────────────────────────────────

class TestErcotDamRecord:
    def test_valid_dam_record(self):
        r = ErcotDamRecord.model_validate(
            {
                "deliveryDate": "2024-01-15",
                "deliveryHour": 12,
                "settlementPoint": "HB_SOUTH",
                "settlementPointType": "HU",
                "settlementPointPrice": 55.25,
            }
        )
        assert r.delivery_hour == 12
        assert r.settlement_point_price == 55.25

    def test_dam_record_has_no_interval_field(self):
        """DAM records do not have deliveryInterval — ensure no spillover from SPP."""
        r = ErcotDamRecord.model_validate(
            {
                "deliveryDate": "2024-01-15",
                "deliveryHour": 1,
                "settlementPoint": "HB_WEST",
                "settlementPointType": "HU",
                "settlementPointPrice": 25.0,
            }
        )
        assert not hasattr(r, "delivery_interval"), "DAM records should not have delivery_interval"


# ── PjmRtLmpRecord ────────────────────────────────────────────────────────────

class TestPjmRtLmpRecord:
    def _valid_payload(self, **overrides) -> dict:
        base = {
            "datetime_beginning_utc": "2024-01-15T00:00:00+00:00",
            "pnode_id": 12345,
            "pnode_name": "AEP GEN HUB",
            "total_lmp_rt": 38.50,
            "system_energy_price_rt": 36.00,
            "congestion_price_rt": 2.00,
            "marginal_loss_price_rt": 0.50,
        }
        base.update(overrides)
        return base

    def test_valid_record(self):
        r = PjmRtLmpRecord.model_validate(self._valid_payload())
        assert r.pnode_name == "AEP GEN HUB"
        assert r.total_lmp_rt == 38.50

    def test_optional_fields_default_none(self):
        r = PjmRtLmpRecord.model_validate(self._valid_payload())
        assert r.voltage is None
        assert r.equipment is None
        assert r.type is None
        assert r.zone is None

    def test_datetime_parsed_to_datetime_object(self):
        from datetime import datetime
        r = PjmRtLmpRecord.model_validate(self._valid_payload())
        assert isinstance(r.datetime_beginning_utc, datetime), (
            "datetime_beginning_utc should be parsed to datetime, not remain a string"
        )

    def test_zero_lmp_is_valid(self):
        r = PjmRtLmpRecord.model_validate(self._valid_payload(total_lmp_rt=0.0))
        assert r.total_lmp_rt == 0.0

    def test_negative_lmp_is_valid(self):
        r = PjmRtLmpRecord.model_validate(self._valid_payload(total_lmp_rt=-50.0))
        assert r.total_lmp_rt == -50.0

    def test_missing_total_lmp_raises(self):
        payload = self._valid_payload()
        del payload["total_lmp_rt"]
        with pytest.raises(ValidationError):
            PjmRtLmpRecord.model_validate(payload)

    def test_invalid_datetime_raises(self):
        with pytest.raises(ValidationError):
            PjmRtLmpRecord.model_validate(self._valid_payload(datetime_beginning_utc="not-a-date"))


# ── PjmDaLmpRecord ────────────────────────────────────────────────────────────

class TestPjmDaLmpRecord:
    def test_valid_da_record(self):
        r = PjmDaLmpRecord.model_validate(
            {
                "datetime_beginning_utc": "2024-01-15T12:00:00+00:00",
                "pnode_id": 99,
                "pnode_name": "DOM HUB",
                "total_lmp_da": 45.0,
                "system_energy_price_da": 43.0,
                "congestion_price_da": 1.5,
                "marginal_loss_price_da": 0.5,
            }
        )
        assert r.total_lmp_da == 45.0


# ── PjmAncillaryRecord ────────────────────────────────────────────────────────

class TestPjmAncillaryRecord:
    def test_valid_ancillary_record(self):
        r = PjmAncillaryRecord.model_validate(
            {
                "datetime_beginning_utc": "2024-01-15T00:00:00+00:00",
                "ancillary_service": "REG",
                "unit": "MW",
                "value": 12.5,
            }
        )
        assert r.ancillary_service == "REG"
        assert r.value == 12.5


# ── PjmPaginatedResponse ─────────────────────────────────────────────────────

class TestPjmPaginatedResponse:
    def test_empty_items(self):
        r = PjmPaginatedResponse.model_validate({"items": []})
        assert r.items == []
        assert r.total_rows is None

    def test_total_rows_optional(self):
        r = PjmPaginatedResponse.model_validate({"items": [], "total_rows": 500})
        assert r.total_rows == 500
