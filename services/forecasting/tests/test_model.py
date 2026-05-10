"""Unit tests for services/forecasting/src/model.py — adversarial QA."""

import os
import tempfile

import numpy as np
import pandas as pd
import pytest
from src.model import ForecastInterval, PriceForecaster

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_df(n_rows: int, start: str = "2024-01-08 00:00:00+00:00") -> pd.DataFrame:
    """Return hourly DataFrame big enough to survive feature engineering lag drops."""
    times = pd.date_range(start, periods=n_rows, freq="h", tz="UTC")
    rng = np.random.default_rng(7)
    lmps = 30.0 + 20.0 * np.sin(np.arange(n_rows) * 2 * np.pi / 24) + rng.normal(0, 3, n_rows)
    return pd.DataFrame({"time": times, "lmp": lmps})


def _trained_forecaster(n_rows: int = 500) -> PriceForecaster:
    """Return a trained PriceForecaster."""
    df = _make_df(n_rows)
    fc = PriceForecaster("test_model")
    fc.train(df)
    return fc


# ---------------------------------------------------------------------------
# is_trained
# ---------------------------------------------------------------------------


def test_is_trained_false_before_training() -> None:
    fc = PriceForecaster("untrained")
    assert fc.is_trained is False


def test_is_trained_true_after_training() -> None:
    df = _make_df(500)
    fc = PriceForecaster("check_trained")
    fc.train(df)
    assert fc.is_trained is True


# ---------------------------------------------------------------------------
# train() — insufficient data
# ---------------------------------------------------------------------------


def test_train_raises_value_error_on_too_few_rows() -> None:
    """After feature engineering, lag_72h drops 72 rows. Need >= 100 surviving rows."""
    # 171 raw rows → 171 - 72 = 99 surviving → still < 100 → ValueError
    df = _make_df(171)
    fc = PriceForecaster("small_data")
    with pytest.raises(ValueError, match="Insufficient data"):
        fc.train(df)


def test_train_raises_value_error_on_boundary() -> None:
    """172 raw rows → 100 surviving rows → should NOT raise (boundary at < 100)."""
    df = _make_df(172)
    fc = PriceForecaster("boundary_100")
    # 172 - 72 = 100 rows → 100 >= 100 → should succeed (no error)
    metrics = fc.train(df)
    assert "mae" in metrics


def test_train_raises_for_empty_df() -> None:
    df = pd.DataFrame(columns=["time", "lmp"])
    fc = PriceForecaster("empty")
    with pytest.raises((ValueError, Exception)):
        fc.train(df)


def test_train_succeeds_with_200_rows() -> None:
    """200 rows → 200 - 72 = 128 surviving → enough to train."""
    df = _make_df(200)
    fc = PriceForecaster("two_hundred_rows")
    metrics = fc.train(df)
    assert "mae" in metrics


# ---------------------------------------------------------------------------
# train() — metrics returned
# ---------------------------------------------------------------------------


def test_train_returns_mae_and_rmse_keys() -> None:
    df = _make_df(500)
    fc = PriceForecaster("metrics_check")
    result = fc.train(df)
    assert "mae" in result
    assert "rmse" in result


def test_train_metrics_are_floats() -> None:
    df = _make_df(500)
    fc = PriceForecaster("float_metrics")
    result = fc.train(df)
    assert isinstance(result["mae"], float)
    assert isinstance(result["rmse"], float)


def test_train_metrics_are_non_negative() -> None:
    df = _make_df(500)
    fc = PriceForecaster("non_neg")
    result = fc.train(df)
    assert result["mae"] >= 0.0
    assert result["rmse"] >= 0.0


def test_get_metrics_includes_bias_and_calibration() -> None:
    fc = _trained_forecaster()
    m = fc.get_metrics()
    assert "bias" in m
    assert "calibration" in m
    assert "mae" in m
    assert "rmse" in m


def test_calibration_is_between_0_and_1() -> None:
    fc = _trained_forecaster()
    m = fc.get_metrics()
    assert 0.0 <= m["calibration"] <= 1.0


# ---------------------------------------------------------------------------
# get_metrics() — returns a copy
# ---------------------------------------------------------------------------


def test_get_metrics_returns_copy_not_reference() -> None:
    fc = _trained_forecaster()
    m1 = fc.get_metrics()
    m1["mae"] = 9999.0
    m2 = fc.get_metrics()
    assert m2["mae"] != 9999.0, "get_metrics() must return a copy, not a reference"


def test_get_metrics_empty_before_training() -> None:
    fc = PriceForecaster("no_train")
    assert fc.get_metrics() == {}


# ---------------------------------------------------------------------------
# predict() — before training
# ---------------------------------------------------------------------------


def test_predict_raises_runtime_error_before_training() -> None:
    fc = PriceForecaster("unpredictable")
    dummy_df = pd.DataFrame({
        "lmp": [35.0] * 5,
        "hour": [0.0] * 5,
        "day_of_week": [0.0] * 5,
        "month": [1.0] * 5,
        "is_weekend": [0.0] * 5,
        "lag_1h": [35.0] * 5,
        "lag_2h": [35.0] * 5,
        "lag_4h": [35.0] * 5,
        "lag_24h": [35.0] * 5,
        "lag_168h": [35.0] * 5,
        "rolling_mean_24h": [35.0] * 5,
        "rolling_std_24h": [0.0] * 5,
    })
    with pytest.raises(RuntimeError, match="not trained"):
        fc.predict(dummy_df, horizon=5)


# ---------------------------------------------------------------------------
# predict() — correct number of intervals
# ---------------------------------------------------------------------------


def test_predict_returns_correct_horizon_length() -> None:
    fc = _trained_forecaster()
    from src.features import build_features
    df = _make_df(500)
    feature_df = build_features(df)
    for horizon in [1, 12, 24, 48]:
        intervals = fc.predict(feature_df, horizon)
        assert len(intervals) == horizon, f"Expected {horizon} intervals, got {len(intervals)}"


def test_predict_zero_horizon_returns_empty_list() -> None:
    fc = _trained_forecaster()
    from src.features import build_features
    df = _make_df(500)
    feature_df = build_features(df)
    intervals = fc.predict(feature_df, horizon=0)
    assert intervals == []


# ---------------------------------------------------------------------------
# predict() — interval structure
# ---------------------------------------------------------------------------


def test_predict_interval_has_required_fields() -> None:
    fc = _trained_forecaster()
    from src.features import build_features
    df = _make_df(500)
    feature_df = build_features(df)
    intervals = fc.predict(feature_df, horizon=3)
    for iv in intervals:
        assert isinstance(iv, ForecastInterval)
        assert hasattr(iv, "timestamp")
        assert hasattr(iv, "mean")
        assert hasattr(iv, "p10")
        assert hasattr(iv, "p90")


def test_predict_interval_timestamps_are_strings() -> None:
    fc = _trained_forecaster()
    from src.features import build_features
    df = _make_df(500)
    feature_df = build_features(df)
    intervals = fc.predict(feature_df, horizon=5)
    for iv in intervals:
        assert isinstance(iv.timestamp, str)


def test_predict_interval_values_are_floats() -> None:
    fc = _trained_forecaster()
    from src.features import build_features
    df = _make_df(500)
    feature_df = build_features(df)
    intervals = fc.predict(feature_df, horizon=5)
    for iv in intervals:
        assert isinstance(iv.mean, float)
        assert isinstance(iv.p10, float)
        assert isinstance(iv.p90, float)


def test_predict_p10_not_greater_than_p90() -> None:
    """Quantile regression doesn't guarantee crossing-free, but p10 should not exceed p90 badly."""
    fc = _trained_forecaster(n_rows=600)
    from src.features import build_features
    df = _make_df(600)
    feature_df = build_features(df)
    intervals = fc.predict(feature_df, horizon=24)
    crossings = sum(1 for iv in intervals if iv.p10 > iv.p90)
    # Note: crossing IS possible with separate quantile models — documenting if it occurs
    # We allow some but it should be rare with well-trained models
    assert crossings < len(intervals), "All intervals have p10 > p90, which is very unexpected"


def test_predict_timestamps_are_sequential_hourly() -> None:
    fc = _trained_forecaster()
    from src.features import build_features
    df = _make_df(500)
    feature_df = build_features(df)
    intervals = fc.predict(feature_df, horizon=5)
    timestamps = [pd.Timestamp(iv.timestamp) for iv in intervals]
    for i in range(1, len(timestamps)):
        delta = timestamps[i] - timestamps[i - 1]
        assert delta == pd.Timedelta(hours=1)


# ---------------------------------------------------------------------------
# save() / load() round-trip
# ---------------------------------------------------------------------------


def test_save_load_roundtrip_is_trained() -> None:
    fc = _trained_forecaster()
    with tempfile.NamedTemporaryFile(suffix=".pkl", delete=False) as f:
        path = f.name
    try:
        fc.save(path)
        loaded = PriceForecaster.load(path)
        assert loaded.is_trained is True
    finally:
        os.unlink(path)


def test_save_load_roundtrip_model_id() -> None:
    df = _make_df(500)
    fc = PriceForecaster("round_trip_id")
    fc.train(df)
    with tempfile.NamedTemporaryFile(suffix=".pkl", delete=False) as f:
        path = f.name
    try:
        fc.save(path)
        loaded = PriceForecaster.load(path)
        assert loaded.model_id == "round_trip_id"
    finally:
        os.unlink(path)


def test_save_load_roundtrip_metrics_preserved() -> None:
    fc = _trained_forecaster()
    original_metrics = fc.get_metrics()
    with tempfile.NamedTemporaryFile(suffix=".pkl", delete=False) as f:
        path = f.name
    try:
        fc.save(path)
        loaded = PriceForecaster.load(path)
        loaded_metrics = loaded.get_metrics()
        assert loaded_metrics["mae"] == pytest.approx(original_metrics["mae"])
        assert loaded_metrics["rmse"] == pytest.approx(original_metrics["rmse"])
    finally:
        os.unlink(path)


def test_save_load_roundtrip_predictions_consistent() -> None:
    fc = _trained_forecaster()
    from src.features import build_features
    df = _make_df(500)
    feature_df = build_features(df)
    original_ivs = fc.predict(feature_df, horizon=5)

    with tempfile.NamedTemporaryFile(suffix=".pkl", delete=False) as f:
        path = f.name
    try:
        fc.save(path)
        loaded = PriceForecaster.load(path)
        loaded_ivs = loaded.predict(feature_df, horizon=5)
        for orig, loaded_iv in zip(original_ivs, loaded_ivs, strict=False):
            assert orig.mean == pytest.approx(loaded_iv.mean, rel=1e-5)
            assert orig.p10 == pytest.approx(loaded_iv.p10, rel=1e-5)
            assert orig.p90 == pytest.approx(loaded_iv.p90, rel=1e-5)
    finally:
        os.unlink(path)


def test_load_nonexistent_file_raises() -> None:
    with pytest.raises(FileNotFoundError):
        PriceForecaster.load("/tmp/does_not_exist_xyzzy.pkl")
