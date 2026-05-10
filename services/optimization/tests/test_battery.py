"""Unit tests for services/optimization/src/battery.py — adversarial QA."""

import pytest
from src.battery import BatteryParams

# ---------------------------------------------------------------------------
# Default values
# ---------------------------------------------------------------------------


def test_default_capacity_mwh() -> None:
    b = BatteryParams(asset_id="test")
    assert b.capacity_mwh == pytest.approx(100.0)


def test_default_max_charge_mw() -> None:
    b = BatteryParams(asset_id="test")
    assert b.max_charge_mw == pytest.approx(25.0)


def test_default_max_discharge_mw() -> None:
    b = BatteryParams(asset_id="test")
    assert b.max_discharge_mw == pytest.approx(25.0)


def test_default_eta_charge() -> None:
    b = BatteryParams(asset_id="test")
    assert b.eta_charge == pytest.approx(0.92)


def test_default_eta_discharge() -> None:
    b = BatteryParams(asset_id="test")
    assert b.eta_discharge == pytest.approx(0.92)


def test_default_soc_min_pct() -> None:
    b = BatteryParams(asset_id="test")
    assert b.soc_min_pct == pytest.approx(0.10)


def test_default_soc_max_pct() -> None:
    b = BatteryParams(asset_id="test")
    assert b.soc_max_pct == pytest.approx(0.90)


def test_default_initial_soc_pct() -> None:
    b = BatteryParams(asset_id="test")
    assert b.initial_soc_pct == pytest.approx(0.50)


def test_default_degradation_per_mwh() -> None:
    b = BatteryParams(asset_id="test")
    assert b.degradation_per_mwh == pytest.approx(2.0)


# ---------------------------------------------------------------------------
# Computed properties — defaults
# ---------------------------------------------------------------------------


def test_soc_min_mwh_default() -> None:
    b = BatteryParams(asset_id="test")
    assert b.soc_min_mwh == pytest.approx(0.10 * 100.0)  # 10.0


def test_soc_max_mwh_default() -> None:
    b = BatteryParams(asset_id="test")
    assert b.soc_max_mwh == pytest.approx(0.90 * 100.0)  # 90.0


def test_initial_soc_mwh_default() -> None:
    b = BatteryParams(asset_id="test")
    assert b.initial_soc_mwh == pytest.approx(0.50 * 100.0)  # 50.0


# ---------------------------------------------------------------------------
# Computed properties — custom values
# ---------------------------------------------------------------------------


def test_soc_min_mwh_custom() -> None:
    b = BatteryParams(asset_id="custom", capacity_mwh=200.0, soc_min_pct=0.15)
    assert b.soc_min_mwh == pytest.approx(0.15 * 200.0)


def test_soc_max_mwh_custom() -> None:
    b = BatteryParams(asset_id="custom", capacity_mwh=200.0, soc_max_pct=0.85)
    assert b.soc_max_mwh == pytest.approx(0.85 * 200.0)


def test_initial_soc_mwh_custom() -> None:
    b = BatteryParams(asset_id="custom", capacity_mwh=50.0, initial_soc_pct=0.25)
    assert b.initial_soc_mwh == pytest.approx(0.25 * 50.0)


def test_soc_min_mwh_zero_percent() -> None:
    b = BatteryParams(asset_id="edge", capacity_mwh=100.0, soc_min_pct=0.0)
    assert b.soc_min_mwh == pytest.approx(0.0)


def test_soc_max_mwh_full_capacity() -> None:
    b = BatteryParams(asset_id="edge", capacity_mwh=100.0, soc_max_pct=1.0)
    assert b.soc_max_mwh == pytest.approx(100.0)


def test_initial_soc_mwh_full() -> None:
    # initial_soc_pct must be within [soc_min_pct, soc_max_pct]
    b = BatteryParams(asset_id="edge", capacity_mwh=100.0, soc_min_pct=0.0, soc_max_pct=1.0, initial_soc_pct=1.0)
    assert b.initial_soc_mwh == pytest.approx(100.0)


def test_initial_soc_mwh_zero() -> None:
    b = BatteryParams(asset_id="edge", capacity_mwh=100.0, soc_min_pct=0.0, soc_max_pct=0.9, initial_soc_pct=0.0)
    assert b.initial_soc_mwh == pytest.approx(0.0)


# ---------------------------------------------------------------------------
# Asymmetric power ratings
# ---------------------------------------------------------------------------


def test_asymmetric_charge_discharge_rates() -> None:
    b = BatteryParams(asset_id="asym", max_charge_mw=10.0, max_discharge_mw=20.0)
    assert b.max_charge_mw == pytest.approx(10.0)
    assert b.max_discharge_mw == pytest.approx(20.0)


# ---------------------------------------------------------------------------
# Pydantic model validates numeric types
# ---------------------------------------------------------------------------


def test_asset_id_required() -> None:
    with pytest.raises(ValueError):
        BatteryParams()  # type: ignore[call-arg]


def test_capacity_zero_raises_validation_error() -> None:
    with pytest.raises(ValueError):
        BatteryParams(asset_id="zero_cap", capacity_mwh=0.0)


def test_very_large_capacity() -> None:
    b = BatteryParams(asset_id="big", capacity_mwh=1_000_000.0, soc_min_pct=0.1, soc_max_pct=0.9)
    assert b.soc_min_mwh == pytest.approx(100_000.0)
    assert b.soc_max_mwh == pytest.approx(900_000.0)


# ---------------------------------------------------------------------------
# Properties are not settable (they are @property)
# ---------------------------------------------------------------------------


def test_soc_min_mwh_is_property_not_field() -> None:
    b = BatteryParams(asset_id="test")
    # It should be a computed property, not a stored attribute in model_fields
    assert "soc_min_mwh" not in b.model_fields


def test_soc_max_mwh_is_property_not_field() -> None:
    b = BatteryParams(asset_id="test")
    assert "soc_max_mwh" not in b.model_fields


def test_initial_soc_mwh_is_property_not_field() -> None:
    b = BatteryParams(asset_id="test")
    assert "initial_soc_mwh" not in b.model_fields
