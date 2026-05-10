"""API-level tests for the optimization service — adversarial QA."""

from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient
from src.battery import BatteryParams
from src.main import app

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _default_battery() -> BatteryParams:
    return BatteryParams(asset_id="test_bess")


def _make_forecast_list(n: int = 24, base_price: float = 40.0) -> list[dict]:
    import pandas as pd
    times = pd.date_range("2024-01-08", periods=n, freq="h", tz="UTC")
    return [
        {
            "timestamp": t.isoformat(),
            "mean": base_price,
            "p10": max(0.0, base_price - 10.0),
            "p90": base_price + 10.0,
        }
        for t in times
    ]


def _make_peak_valley_forecast(n: int = 24) -> list[dict]:
    import pandas as pd
    times = pd.date_range("2024-01-08", periods=n, freq="h", tz="UTC")
    return [
        {
            "timestamp": t.isoformat(),
            "mean": 20.0 if i < n // 2 else 80.0,
            "p10": 10.0 if i < n // 2 else 70.0,
            "p90": 30.0 if i < n // 2 else 90.0,
        }
        for i, t in enumerate(times)
    ]


VALID_OPTIMIZE_BODY = {
    "asset_id": "bess_01",
    "forecasts": {"DA_ENERGY": _make_forecast_list(24)},
    "horizon_hours": 24,
    "markets": ["DA_ENERGY"],
}


# ---------------------------------------------------------------------------
# GET /health
# ---------------------------------------------------------------------------


def test_health_returns_200() -> None:
    client = TestClient(app)
    resp = client.get("/health")
    assert resp.status_code == 200


def test_health_returns_status_ok() -> None:
    client = TestClient(app)
    resp = client.get("/health")
    assert resp.json() == {"status": "ok"}


# ---------------------------------------------------------------------------
# GET /battery/{asset_id}
# ---------------------------------------------------------------------------


def test_get_battery_returns_200() -> None:
    with patch("src.main.get_battery_params", return_value=_default_battery()):
        client = TestClient(app)
        resp = client.get("/battery/test_bess")
    assert resp.status_code == 200


def test_get_battery_returns_battery_params_shape() -> None:
    with patch("src.main.get_battery_params", return_value=_default_battery()):
        client = TestClient(app)
        resp = client.get("/battery/test_bess")
    data = resp.json()
    assert "asset_id" in data
    assert "capacity_mwh" in data
    assert "max_charge_mw" in data
    assert "max_discharge_mw" in data


def test_get_battery_returns_default_capacity() -> None:
    with patch("src.main.get_battery_params", return_value=_default_battery()):
        client = TestClient(app)
        resp = client.get("/battery/test_bess")
    data = resp.json()
    assert data["capacity_mwh"] == pytest.approx(100.0)


def test_get_battery_echoes_asset_id() -> None:
    battery = BatteryParams(asset_id="custom_bess_42")
    with patch("src.main.get_battery_params", return_value=battery):
        client = TestClient(app)
        resp = client.get("/battery/custom_bess_42")
    assert resp.json()["asset_id"] == "custom_bess_42"


def test_get_battery_redis_unavailable_returns_defaults() -> None:
    """When Redis is down, get_battery_params returns defaults — should still return 200."""
    # Don't patch — let it try Redis (which will fail) and return defaults
    client = TestClient(app)
    resp = client.get("/battery/any_asset")
    assert resp.status_code == 200


# ---------------------------------------------------------------------------
# POST /optimize — valid input
# ---------------------------------------------------------------------------


def test_optimize_valid_body_returns_200() -> None:
    with patch("src.main.get_battery_params", return_value=_default_battery()):
        client = TestClient(app)
        resp = client.post("/optimize", json=VALID_OPTIMIZE_BODY)
    assert resp.status_code == 200


def test_optimize_response_has_required_fields() -> None:
    with patch("src.main.get_battery_params", return_value=_default_battery()):
        client = TestClient(app)
        resp = client.post("/optimize", json=VALID_OPTIMIZE_BODY)
    data = resp.json()
    assert "asset_id" in data
    assert "intervals" in data
    assert "total_expected_revenue_dollars" in data
    assert "solver_status" in data


def test_optimize_asset_id_echoed() -> None:
    with patch("src.main.get_battery_params", return_value=_default_battery()):
        client = TestClient(app)
        resp = client.post("/optimize", json=VALID_OPTIMIZE_BODY)
    assert resp.json()["asset_id"] == "bess_01"


def test_optimize_solver_status_present_and_string() -> None:
    with patch("src.main.get_battery_params", return_value=_default_battery()):
        client = TestClient(app)
        resp = client.post("/optimize", json=VALID_OPTIMIZE_BODY)
    status = resp.json()["solver_status"]
    assert isinstance(status, str)
    assert len(status) > 0


def test_optimize_total_revenue_equals_sum_of_intervals() -> None:
    with patch("src.main.get_battery_params", return_value=_default_battery()):
        client = TestClient(app)
        resp = client.post("/optimize", json=VALID_OPTIMIZE_BODY)
    data = resp.json()
    total = data["total_expected_revenue_dollars"]
    interval_sum = sum(iv["expected_revenue_dollars"] for iv in data["intervals"])
    assert total == pytest.approx(interval_sum, rel=1e-5)


def test_optimize_interval_has_required_fields() -> None:
    with patch("src.main.get_battery_params", return_value=_default_battery()):
        client = TestClient(app)
        resp = client.post("/optimize", json=VALID_OPTIMIZE_BODY)
    for iv in resp.json()["intervals"]:
        assert "timestamp" in iv
        assert "charge_mw" in iv
        assert "discharge_mw" in iv
        assert "market" in iv
        assert "expected_revenue_dollars" in iv


# ---------------------------------------------------------------------------
# POST /optimize — market not in forecasts (should skip, not 500)
# ---------------------------------------------------------------------------


def test_optimize_missing_market_in_forecasts_returns_200() -> None:
    body = {
        "asset_id": "bess_01",
        "forecasts": {"DA_ENERGY": _make_forecast_list(24)},
        "horizon_hours": 24,
        "markets": ["RT_ENERGY"],  # RT_ENERGY not in forecasts
    }
    with patch("src.main.get_battery_params", return_value=_default_battery()):
        client = TestClient(app)
        resp = client.post("/optimize", json=body)
    assert resp.status_code == 200


def test_optimize_missing_market_returns_empty_intervals() -> None:
    body = {
        "asset_id": "bess_01",
        "forecasts": {"DA_ENERGY": _make_forecast_list(24)},
        "horizon_hours": 24,
        "markets": ["RT_ENERGY"],
    }
    with patch("src.main.get_battery_params", return_value=_default_battery()):
        client = TestClient(app)
        resp = client.post("/optimize", json=body)
    assert resp.json()["intervals"] == []


def test_optimize_missing_market_total_revenue_is_zero() -> None:
    body = {
        "asset_id": "bess_01",
        "forecasts": {},
        "horizon_hours": 24,
        "markets": ["DA_ENERGY"],
    }
    with patch("src.main.get_battery_params", return_value=_default_battery()):
        client = TestClient(app)
        resp = client.post("/optimize", json=body)
    assert resp.status_code == 200
    assert resp.json()["total_expected_revenue_dollars"] == pytest.approx(0.0)


# ---------------------------------------------------------------------------
# POST /optimize — empty markets list
# ---------------------------------------------------------------------------


def test_optimize_empty_markets_returns_200() -> None:
    body = {
        "asset_id": "bess_01",
        "forecasts": {"DA_ENERGY": _make_forecast_list(24)},
        "horizon_hours": 24,
        "markets": [],
    }
    with patch("src.main.get_battery_params", return_value=_default_battery()):
        client = TestClient(app)
        resp = client.post("/optimize", json=body)
    assert resp.status_code == 200


def test_optimize_empty_markets_returns_empty_intervals() -> None:
    body = {
        "asset_id": "bess_01",
        "forecasts": {"DA_ENERGY": _make_forecast_list(24)},
        "horizon_hours": 24,
        "markets": [],
    }
    with patch("src.main.get_battery_params", return_value=_default_battery()):
        client = TestClient(app)
        resp = client.post("/optimize", json=body)
    assert resp.json()["intervals"] == []


# ---------------------------------------------------------------------------
# POST /optimize — horizon_hours doesn't need to match forecast list length
# ---------------------------------------------------------------------------


def test_optimize_horizon_mismatch_uses_forecast_list_length() -> None:
    """horizon_hours is passed in but solver uses len(forecast_list) — should not error."""
    body = {
        "asset_id": "bess_01",
        "forecasts": {"DA_ENERGY": _make_forecast_list(12)},  # 12 intervals
        "horizon_hours": 24,  # Different from forecast list length
        "markets": ["DA_ENERGY"],
    }
    with patch("src.main.get_battery_params", return_value=_default_battery()):
        client = TestClient(app)
        resp = client.post("/optimize", json=body)
    assert resp.status_code == 200
    # Solver uses forecast_list length (12), not horizon_hours
    assert len(resp.json()["intervals"]) == 12


# ---------------------------------------------------------------------------
# POST /optimize — invalid input
# ---------------------------------------------------------------------------


def test_optimize_missing_asset_id_returns_422() -> None:
    body = {k: v for k, v in VALID_OPTIMIZE_BODY.items() if k != "asset_id"}
    client = TestClient(app)
    resp = client.post("/optimize", json=body)
    assert resp.status_code == 422


def test_optimize_missing_markets_field_returns_422() -> None:
    body = {k: v for k, v in VALID_OPTIMIZE_BODY.items() if k != "markets"}
    client = TestClient(app)
    resp = client.post("/optimize", json=body)
    assert resp.status_code == 422


def test_optimize_empty_body_returns_422() -> None:
    client = TestClient(app)
    resp = client.post("/optimize", json={})
    assert resp.status_code == 422


# ---------------------------------------------------------------------------
# POST /optimize — multiple markets
# ---------------------------------------------------------------------------


def test_optimize_multiple_markets_merges_intervals() -> None:
    body = {
        "asset_id": "bess_01",
        "forecasts": {
            "DA_ENERGY": _make_forecast_list(24, base_price=40.0),
            "RT_ENERGY": _make_forecast_list(24, base_price=50.0),
        },
        "horizon_hours": 24,
        "markets": ["DA_ENERGY", "RT_ENERGY"],
    }
    with patch("src.main.get_battery_params", return_value=_default_battery()):
        client = TestClient(app)
        resp = client.post("/optimize", json=body)
    assert resp.status_code == 200
    # Merged intervals: best revenue per timestamp across markets
    data = resp.json()
    assert len(data["intervals"]) == 24


def test_optimize_total_revenue_is_float() -> None:
    with patch("src.main.get_battery_params", return_value=_default_battery()):
        client = TestClient(app)
        resp = client.post("/optimize", json=VALID_OPTIMIZE_BODY)
    total = resp.json()["total_expected_revenue_dollars"]
    assert isinstance(total, int | float)


# ---------------------------------------------------------------------------
# Regression: intervals are sorted by timestamp
# ---------------------------------------------------------------------------


def test_optimize_intervals_sorted_by_timestamp() -> None:
    with patch("src.main.get_battery_params", return_value=_default_battery()):
        client = TestClient(app)
        resp = client.post("/optimize", json=VALID_OPTIMIZE_BODY)
    timestamps = [iv["timestamp"] for iv in resp.json()["intervals"]]
    assert timestamps == sorted(timestamps)
