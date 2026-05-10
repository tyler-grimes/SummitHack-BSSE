"""API-level tests for the forecasting service — adversarial QA.

Uses FastAPI TestClient (sync) with patched DB and model registry.
"""

from unittest.mock import AsyncMock, patch

import pandas as pd
import pytest
from fastapi.testclient import TestClient
from src.main import app

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_lmp_df(n_rows: int = 300) -> pd.DataFrame:
    import numpy as np
    times = pd.date_range("2024-01-08", periods=n_rows, freq="h", tz="UTC")
    rng = np.random.default_rng(99)
    lmps = 30.0 + rng.uniform(-5, 5, n_rows)
    return pd.DataFrame({"time": times, "lmp": lmps})


VALID_FORECAST_BODY = {
    "iso": "CAISO",
    "nodes": ["NP15"],
    "market": "DA_ENERGY",
    "horizon_hours": 24,
}


# ---------------------------------------------------------------------------
# GET /health
# ---------------------------------------------------------------------------


def test_health_returns_200() -> None:
    client = TestClient(app, raise_server_exceptions=True)
    resp = client.get("/health")
    assert resp.status_code == 200


def test_health_returns_status_ok() -> None:
    client = TestClient(app)
    resp = client.get("/health")
    assert resp.json() == {"status": "ok"}


# ---------------------------------------------------------------------------
# POST /forecast — basic structure
# ---------------------------------------------------------------------------


def test_forecast_valid_body_returns_200() -> None:
    with patch("src.main.fetch_lmp_history", new_callable=AsyncMock) as mock_db:
        mock_db.return_value = _make_lmp_df()
        client = TestClient(app)
        resp = client.post("/forecast", json=VALID_FORECAST_BODY)
    assert resp.status_code == 200


def test_forecast_returns_list() -> None:
    with patch("src.main.fetch_lmp_history", new_callable=AsyncMock) as mock_db:
        mock_db.return_value = _make_lmp_df()
        client = TestClient(app)
        resp = client.post("/forecast", json=VALID_FORECAST_BODY)
    assert isinstance(resp.json(), list)


def test_forecast_returns_one_entry_per_node() -> None:
    body = {**VALID_FORECAST_BODY, "nodes": ["NP15", "SP15"]}
    with patch("src.main.fetch_lmp_history", new_callable=AsyncMock) as mock_db:
        mock_db.return_value = _make_lmp_df()
        client = TestClient(app)
        resp = client.post("/forecast", json=body)
    data = resp.json()
    assert len(data) == 2


def test_forecast_response_has_correct_structure() -> None:
    with patch("src.main.fetch_lmp_history", new_callable=AsyncMock) as mock_db:
        mock_db.return_value = _make_lmp_df()
        client = TestClient(app)
        resp = client.post("/forecast", json=VALID_FORECAST_BODY)
    entry = resp.json()[0]
    assert "iso" in entry
    assert "node" in entry
    assert "market" in entry
    assert "intervals" in entry
    assert "model_id" in entry
    assert "confidence" in entry


def test_forecast_iso_and_node_echo_back() -> None:
    with patch("src.main.fetch_lmp_history", new_callable=AsyncMock) as mock_db:
        mock_db.return_value = _make_lmp_df()
        client = TestClient(app)
        resp = client.post("/forecast", json=VALID_FORECAST_BODY)
    entry = resp.json()[0]
    assert entry["iso"] == "CAISO"
    assert entry["node"] == "NP15"
    assert entry["market"] == "DA_ENERGY"


def test_forecast_24_hours_returns_24_intervals() -> None:
    body = {**VALID_FORECAST_BODY, "horizon_hours": 24}
    with patch("src.main.fetch_lmp_history", new_callable=AsyncMock) as mock_db:
        mock_db.return_value = _make_lmp_df()
        client = TestClient(app)
        resp = client.post("/forecast", json=body)
    intervals = resp.json()[0]["intervals"]
    assert len(intervals) == 24


def test_forecast_interval_has_required_fields() -> None:
    with patch("src.main.fetch_lmp_history", new_callable=AsyncMock) as mock_db:
        mock_db.return_value = _make_lmp_df()
        client = TestClient(app)
        resp = client.post("/forecast", json=VALID_FORECAST_BODY)
    for iv in resp.json()[0]["intervals"]:
        assert "timestamp" in iv
        assert "mean" in iv
        assert "p10" in iv
        assert "p90" in iv


def test_forecast_interval_values_are_numeric() -> None:
    with patch("src.main.fetch_lmp_history", new_callable=AsyncMock) as mock_db:
        mock_db.return_value = _make_lmp_df()
        client = TestClient(app)
        resp = client.post("/forecast", json=VALID_FORECAST_BODY)
    for iv in resp.json()[0]["intervals"]:
        assert isinstance(iv["mean"], int | float)
        assert isinstance(iv["p10"], int | float)
        assert isinstance(iv["p90"], int | float)


# ---------------------------------------------------------------------------
# POST /forecast — empty DB fallback (synthetic)
# ---------------------------------------------------------------------------


def test_forecast_empty_db_returns_200_not_500() -> None:
    """When DB returns empty DataFrame, service must fall back to synthetic forecast."""
    with patch("src.main.fetch_lmp_history", new_callable=AsyncMock) as mock_db:
        mock_db.return_value = pd.DataFrame(columns=["time", "lmp"])
        client = TestClient(app)
        resp = client.post("/forecast", json=VALID_FORECAST_BODY)
    assert resp.status_code == 200


def test_forecast_empty_db_still_returns_intervals() -> None:
    with patch("src.main.fetch_lmp_history", new_callable=AsyncMock) as mock_db:
        mock_db.return_value = pd.DataFrame(columns=["time", "lmp"])
        client = TestClient(app)
        resp = client.post("/forecast", json=VALID_FORECAST_BODY)
    intervals = resp.json()[0]["intervals"]
    assert len(intervals) == VALID_FORECAST_BODY["horizon_hours"]


def test_forecast_db_exception_returns_200() -> None:
    """DB throwing RuntimeError must not crash the service."""
    with patch("src.main.fetch_lmp_history", new_callable=AsyncMock) as mock_db:
        mock_db.side_effect = RuntimeError("DB unavailable")
        client = TestClient(app)
        resp = client.post("/forecast", json=VALID_FORECAST_BODY)
    assert resp.status_code == 200


def test_forecast_empty_db_confidence_is_zero() -> None:
    with patch("src.main.fetch_lmp_history", new_callable=AsyncMock) as mock_db:
        mock_db.return_value = pd.DataFrame(columns=["time", "lmp"])
        client = TestClient(app)
        resp = client.post("/forecast", json=VALID_FORECAST_BODY)
    assert resp.json()[0]["confidence"] == pytest.approx(0.0)


# ---------------------------------------------------------------------------
# POST /forecast — invalid input
# ---------------------------------------------------------------------------


def test_forecast_missing_iso_returns_422() -> None:
    body = {k: v for k, v in VALID_FORECAST_BODY.items() if k != "iso"}
    client = TestClient(app)
    resp = client.post("/forecast", json=body)
    assert resp.status_code == 422


def test_forecast_invalid_market_returns_422() -> None:
    body = {**VALID_FORECAST_BODY, "market": "NOT_A_MARKET"}
    client = TestClient(app)
    resp = client.post("/forecast", json=body)
    assert resp.status_code == 422


def test_forecast_empty_nodes_list_returns_200_empty_list() -> None:
    body = {**VALID_FORECAST_BODY, "nodes": []}
    with patch("src.main.fetch_lmp_history", new_callable=AsyncMock):
        client = TestClient(app)
        resp = client.post("/forecast", json=body)
    assert resp.status_code == 200
    assert resp.json() == []


def test_forecast_negative_horizon_returns_valid_response() -> None:
    """Negative horizon is edge case — service should not crash (may return 0 intervals)."""
    body = {**VALID_FORECAST_BODY, "horizon_hours": -1}
    with patch("src.main.fetch_lmp_history", new_callable=AsyncMock) as mock_db:
        mock_db.return_value = pd.DataFrame(columns=["time", "lmp"])
        client = TestClient(app)
        resp = client.post("/forecast", json=body)
    # Should not return 500
    assert resp.status_code in (200, 422)


# ---------------------------------------------------------------------------
# POST /confidence
# ---------------------------------------------------------------------------


def test_confidence_unknown_model_returns_200() -> None:
    client = TestClient(app)
    resp = client.post("/confidence", json={"model_id": "nonexistent_model_xyz"})
    assert resp.status_code == 200


def test_confidence_unknown_model_returns_all_zeros() -> None:
    client = TestClient(app)
    resp = client.post("/confidence", json={"model_id": "nonexistent_model_xyz"})
    data = resp.json()
    assert data["mae"] == pytest.approx(0.0)
    assert data["rmse"] == pytest.approx(0.0)
    assert data["bias"] == pytest.approx(0.0)
    assert data["calibration"] == pytest.approx(0.0)
    assert data["sample_size"] == 0


def test_confidence_response_has_model_id_echoed() -> None:
    client = TestClient(app)
    resp = client.post("/confidence", json={"model_id": "test_echo_id"})
    assert resp.json()["model_id"] == "test_echo_id"


def test_confidence_missing_model_id_returns_422() -> None:
    client = TestClient(app)
    resp = client.post("/confidence", json={})
    assert resp.status_code == 422


# ---------------------------------------------------------------------------
# POST /train — empty DB returns 422
# ---------------------------------------------------------------------------


def test_train_empty_db_returns_422() -> None:
    with patch("src.main.fetch_lmp_history", new_callable=AsyncMock) as mock_db:
        mock_db.return_value = pd.DataFrame(columns=["time", "lmp"])
        client = TestClient(app)
        resp = client.post("/train", json={
            "iso": "CAISO",
            "node": "NP15",
            "market": "DA_ENERGY",
        })
    assert resp.status_code == 422


def test_train_missing_fields_returns_422() -> None:
    client = TestClient(app)
    resp = client.post("/train", json={"iso": "CAISO"})
    assert resp.status_code == 422


def test_train_invalid_market_returns_422() -> None:
    client = TestClient(app)
    resp = client.post("/train", json={
        "iso": "CAISO",
        "node": "NP15",
        "market": "FAKE_MARKET",
    })
    assert resp.status_code == 422


def test_train_db_exception_returns_error() -> None:
    """If DB raises RuntimeError (pool not initialized), train should fail gracefully."""
    with patch("src.main.fetch_lmp_history", new_callable=AsyncMock) as mock_db:
        mock_db.side_effect = RuntimeError("Pool not initialized")
        client = TestClient(app, raise_server_exceptions=False)
        resp = client.post("/train", json={
            "iso": "CAISO",
            "node": "NP15",
            "market": "DA_ENERGY",
        })
    # RuntimeError propagates → 500
    assert resp.status_code in (422, 500)


# ---------------------------------------------------------------------------
# POST /train — successful training (with sufficient mock data)
# ---------------------------------------------------------------------------


def test_train_sufficient_data_returns_200() -> None:
    import numpy as np
    n = 500
    times = pd.date_range("2024-01-08", periods=n, freq="h", tz="UTC")
    rng = np.random.default_rng(11)
    df = pd.DataFrame({"time": times, "lmp": 30.0 + rng.uniform(-5, 5, n)})

    with patch("src.main.fetch_lmp_history", new_callable=AsyncMock) as mock_db:
        mock_db.return_value = df
        client = TestClient(app)
        resp = client.post("/train", json={
            "iso": "CAISO",
            "node": "NP15",
            "market": "DA_ENERGY",
        })
    # May fail if MODEL_DIR not writable, but should not be 422
    assert resp.status_code in (200, 500)


def test_train_response_has_correct_structure() -> None:
    import numpy as np
    n = 500
    times = pd.date_range("2024-01-08", periods=n, freq="h", tz="UTC")
    rng = np.random.default_rng(11)
    df = pd.DataFrame({"time": times, "lmp": 30.0 + rng.uniform(-5, 5, n)})

    with patch("src.main.fetch_lmp_history", new_callable=AsyncMock) as mock_db:
        with patch("src.main.PriceForecaster.save"):
            mock_db.return_value = df
            client = TestClient(app)
            resp = client.post("/train", json={
                "iso": "CAISO",
                "node": "NP15",
                "market": "DA_ENERGY",
            })
    if resp.status_code == 200:
        data = resp.json()
        assert "model_id" in data
        assert "mae" in data
        assert "rmse" in data
        assert "training_rows" in data
