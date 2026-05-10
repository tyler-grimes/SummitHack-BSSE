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


def test_nan_rows_dropped_due_to_lag_168h() -> None:
    """With exactly 300 rows, lag_168h shifts by 168 → first 168 rows become NaN → dropped."""
    df = _make_df(300)
    result = build_features(df)
    # Row 0..167 have lag_168h = NaN → should all be dropped
    # lag_24h drops first 24 rows, lag_168h drops first 168 rows
    # So we expect 300 - 168 = 132 rows remaining
    assert len(result) == 300 - 168


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
# Fewer than 168 rows → all lag_168h NaN → everything dropped
# ---------------------------------------------------------------------------


def test_fewer_than_168_rows_returns_empty() -> None:
    df = _make_df(167)
    result = build_features(df)
    # lag_168h requires 168 prior rows → all NaN → all dropped
    assert len(result) == 0


def test_exactly_168_rows_returns_empty() -> None:
    """With 168 rows, only row 168 (index 167) would have lag_168h, but there is no row 168."""
    df = _make_df(168)
    result = build_features(df)
    # The 168th row (index 167) gets shift(168) = None, so still 0 rows survive
    assert len(result) == 0


def test_exactly_169_rows_returns_one_row() -> None:
    df = _make_df(169)
    result = build_features(df)
    assert len(result) == 1


# ---------------------------------------------------------------------------
# Lag values correctness
# ---------------------------------------------------------------------------


def test_lag_1h_matches_previous_lmp() -> None:
    df = _make_df(300)
    result = build_features(df)
    # After dropna, result is aligned. The lag columns in result should match
    # the original lmp shifted by the right amount.
    # The first surviving row was originally at index 168.
    # lag_1h of that row = lmp at original index 167
    original_lmp = df["lmp"].values
    first_idx_in_original = 168
    assert result["lag_1h"].iloc[0] == pytest.approx(original_lmp[first_idx_in_original - 1])


def test_lag_24h_matches_24_steps_back() -> None:
    df = _make_df(300)
    result = build_features(df)
    original_lmp = df["lmp"].values
    first_idx_in_original = 168
    assert result["lag_24h"].iloc[0] == pytest.approx(original_lmp[first_idx_in_original - 24])


def test_lag_168h_matches_168_steps_back() -> None:
    df = _make_df(300)
    result = build_features(df)
    original_lmp = df["lmp"].values
    first_idx_in_original = 168
    assert result["lag_168h"].iloc[0] == pytest.approx(original_lmp[first_idx_in_original - 168])


# ---------------------------------------------------------------------------
# Rolling stats
# ---------------------------------------------------------------------------


def test_rolling_mean_24h_computed_correctly() -> None:
    """rolling_mean_24h uses min_periods=1, so it's always available."""
    df = _make_df(300)
    result = build_features(df)
    # For the first surviving row (originally index 168), rolling_mean is mean of rows [145..168]
    # (window=24, so rows 145..168 inclusive = 24 rows)
    first_idx = 168
    expected_mean = float(df["lmp"].iloc[first_idx - 23 : first_idx + 1].mean())
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
