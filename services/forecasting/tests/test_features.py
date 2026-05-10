"""Unit tests for services/forecasting/src/features.py — adversarial QA."""

import numpy as np
import pandas as pd
import pytest
from src.features import build_features

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

FEATURE_COLS = [
    "hour",
    "day_of_week",
    "month",
    "is_weekend",
    "lag_1h",
    "lag_2h",
    "lag_4h",
    "lag_24h",
    "lag_48h",
    "lag_168h",
    "rolling_mean_24h",
    "rolling_std_24h",
]


def _make_df(n_rows: int, start: str = "2024-01-08 00:00:00+00:00") -> pd.DataFrame:
    """Return a DataFrame with `n_rows` hourly records starting on a Monday."""
    times = pd.date_range(start, periods=n_rows, freq="h", tz="UTC")
    rng = np.random.default_rng(42)
    lmps = rng.uniform(20.0, 60.0, size=n_rows)
    return pd.DataFrame({"time": times, "lmp": lmps})


# ---------------------------------------------------------------------------
# Column presence
# ---------------------------------------------------------------------------


def test_all_feature_columns_present() -> None:
    df = _make_df(300)
    result = build_features(df)
    for col in FEATURE_COLS:
        assert col in result.columns, f"Missing column: {col}"
    assert "lmp" in result.columns


def test_returns_exactly_expected_columns_plus_time_and_lmp() -> None:
    df = _make_df(300)
    result = build_features(df)
    expected = set(FEATURE_COLS) | {"time", "lmp"}
    assert expected.issubset(set(result.columns))


# ---------------------------------------------------------------------------
# NaN dropping: first 168 rows will have NaN lag_168h
# ---------------------------------------------------------------------------


def test_nan_rows_dropped_due_to_binding_constraint() -> None:
    """With 300 rows, lag_72h (shift 72) is the binding constraint → first 72 rows dropped."""
    df = _make_df(300)
    result = build_features(df)
    # lag_72h = shift(72) → first 72 rows NaN → dropped
    assert len(result) == 300 - 72


def test_no_nan_in_output() -> None:
    df = _make_df(300)
    result = build_features(df)
    assert not result[FEATURE_COLS].isnull().any().any()


# ---------------------------------------------------------------------------
# is_weekend values
# ---------------------------------------------------------------------------


def test_is_weekend_saturday_is_one() -> None:
    # 2024-01-06 is a Saturday
    # Build a minimal 300-row df starting from far enough back that Sat appears
    start_sat = "2024-01-06 00:00:00+00:00"
    df2 = _make_df(300, start=start_sat)
    result = build_features(df2)
    # Saturdays: dayofweek == 5
    sat_rows = result[result["time"].dt.dayofweek == 5]
    assert (sat_rows["is_weekend"] == 1.0).all()


def test_is_weekend_sunday_is_one() -> None:
    start_sun = "2024-01-07 00:00:00+00:00"
    df = _make_df(300, start=start_sun)
    result = build_features(df)
    sun_rows = result[result["time"].dt.dayofweek == 6]
    assert (sun_rows["is_weekend"] == 1.0).all()


def test_is_weekend_weekday_is_zero() -> None:
    # Monday 2024-01-08
    start_mon = "2024-01-08 00:00:00+00:00"
    df = _make_df(300, start=start_mon)
    result = build_features(df)
    weekday_rows = result[result["time"].dt.dayofweek < 5]
    assert (weekday_rows["is_weekend"] == 0.0).all()


# ---------------------------------------------------------------------------
# Empty DataFrame
# ---------------------------------------------------------------------------


def test_empty_dataframe_returns_empty() -> None:
    df = pd.DataFrame(columns=["time", "lmp"])
    result = build_features(df)
    assert isinstance(result, pd.DataFrame)
    assert len(result) == 0


# ---------------------------------------------------------------------------
# Fewer than 49 rows → all lag_48h NaN → everything dropped
# (lag_168h has a soft fallback to lag_24h so it no longer drives the cut)
# ---------------------------------------------------------------------------


def test_fewer_than_73_rows_returns_empty() -> None:
    df = _make_df(72)
    result = build_features(df)
    # lag_72h = shift(72) → all 72 rows have NaN lag_72h → all dropped
    assert len(result) == 0


def test_exactly_73_rows_returns_one_row() -> None:
    df = _make_df(73)
    result = build_features(df)
    # lag_72h = shift(72) → row 72 is the first with all lags and rolling stats satisfied → 1 row survives
    assert len(result) == 1


def test_168_rows_returns_data() -> None:
    """168 rows with lag_72h as binding constraint → 168 - 72 = 96 surviving rows."""
    df = _make_df(168)
    result = build_features(df)
    assert len(result) == 168 - 72


# ---------------------------------------------------------------------------
# Lag values correctness
# ---------------------------------------------------------------------------


def test_lag_1h_matches_previous_lmp() -> None:
    df = _make_df(300)
    result = build_features(df)
    # First surviving row originally at index 72 (lag_72h is binding constraint).
    # lag_1h of that row = lmp at original index 71.
    original_lmp = df["lmp"].values
    first_idx_in_original = 72
    assert result["lag_1h"].iloc[0] == pytest.approx(original_lmp[first_idx_in_original - 1])


def test_lag_24h_matches_24_steps_back() -> None:
    df = _make_df(300)
    result = build_features(df)
    original_lmp = df["lmp"].values
    first_idx_in_original = 72
    assert result["lag_24h"].iloc[0] == pytest.approx(original_lmp[first_idx_in_original - 24])


def test_lag_48h_matches_48_steps_back() -> None:
    df = _make_df(300)
    result = build_features(df)
    original_lmp = df["lmp"].values
    first_idx_in_original = 72
    assert result["lag_48h"].iloc[0] == pytest.approx(original_lmp[first_idx_in_original - 48])


def test_lag_168h_falls_back_to_lag_24h_when_history_is_short() -> None:
    """With only 100 rows, lag_168h (shift 168) would be NaN; fillna uses lag_24h instead."""
    df = _make_df(100)
    result = build_features(df)
    # All surviving rows (indices 72..99) have lag_168h filled from lag_24h
    assert not result["lag_168h"].isnull().any()
    # For first surviving row at original idx 72: lag_168h == lag_24h == lmp[48]
    original_lmp = df["lmp"].values
    assert result["lag_168h"].iloc[0] == pytest.approx(original_lmp[72 - 24])


# ---------------------------------------------------------------------------
# Rolling stats
# ---------------------------------------------------------------------------


def test_rolling_mean_24h_computed_correctly() -> None:
    """rolling_mean_24h is computed on shift(1) with full min_periods=24.
    At original index 72, shifted lmp is lmp[71], and rolling(24) covers
    shifted indices [49..72] = lmp[48..71]."""
    df = _make_df(300)
    result = build_features(df)
    first_idx = 72
    # shifted series at index i = lmp[i-1]; rolling(24) at index 72 uses
    # shifted[49..72] = lmp[48..71]
    expected_mean = float(df["lmp"].iloc[first_idx - 24 : first_idx].mean())
    assert result["rolling_mean_24h"].iloc[0] == pytest.approx(expected_mean, rel=1e-4)


def test_rolling_std_24h_fillna_zero() -> None:
    """With min_periods=1, std with 1 element returns NaN which is filled to 0.0."""
    df2 = _make_df(300)
    result = build_features(df2)
    # rolling_std_24h should never be NaN
    assert not result["rolling_std_24h"].isnull().any()


def test_rolling_std_24h_with_constant_prices_is_zero() -> None:
    """All same LMP → rolling std should be 0."""
    times = pd.date_range("2024-01-08", periods=300, freq="h", tz="UTC")
    df = pd.DataFrame({"time": times, "lmp": [50.0] * 300})
    result = build_features(df)
    assert (result["rolling_std_24h"].abs() < 1e-10).all()


# ---------------------------------------------------------------------------
# Time feature correctness
# ---------------------------------------------------------------------------


def test_hour_column_values_match_time() -> None:
    df = _make_df(300)
    result = build_features(df)
    assert (result["hour"] == result["time"].dt.hour.astype(float)).all()


def test_month_column_values_match_time() -> None:
    df = _make_df(300)
    result = build_features(df)
    assert (result["month"] == result["time"].dt.month.astype(float)).all()


# ---------------------------------------------------------------------------
# Index reset
# ---------------------------------------------------------------------------


def test_output_index_is_reset() -> None:
    df = _make_df(300)
    result = build_features(df)
    assert list(result.index) == list(range(len(result)))
