import math
import pickle
from typing import Any

import numpy as np
import pandas as pd
import xgboost as xgb
from sklearn.metrics import mean_absolute_error, mean_squared_error

from .features import build_features

FEATURE_COLS: list[str] = [
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

# Keep 20% of data for hold-out evaluation
_TRAIN_SPLIT: float = 0.8


def _make_quantile_model(alpha: float) -> xgb.XGBRegressor:
    return xgb.XGBRegressor(
        objective="reg:quantileerror",
        quantile_alpha=alpha,
        n_estimators=200,
        max_depth=6,
        learning_rate=0.05,
        n_jobs=-1,
        tree_method="hist",
    )


class ForecastInterval:
    __slots__ = ("mean", "p10", "p90", "timestamp")

    timestamp: str
    mean: float
    p10: float
    p90: float

    def __init__(self, timestamp: str, mean: float, p10: float, p90: float) -> None:
        self.timestamp = timestamp
        self.mean = mean
        self.p10 = p10
        self.p90 = p90


class PriceForecaster:
    def __init__(self, model_id: str) -> None:
        self.model_id = model_id
        self._model_p10: xgb.XGBRegressor | None = None
        self._model_p50: xgb.XGBRegressor | None = None
        self._model_p90: xgb.XGBRegressor | None = None
        self._metrics: dict[str, float] = {}

    @property
    def is_trained(self) -> bool:
        return self._model_p50 is not None

    def get_metrics(self) -> dict[str, float]:
        return dict(self._metrics)

    def train(self, df: pd.DataFrame) -> dict[str, float]:
        features = build_features(df)
        if len(features) < 50:
            raise ValueError(
                f"Insufficient data for training: {len(features)} rows after feature engineering"
            )

        split_idx = int(len(features) * _TRAIN_SPLIT)
        train_df = features.iloc[:split_idx]
        test_df = features.iloc[split_idx:]

        X_train: pd.DataFrame = train_df[FEATURE_COLS]
        y_train: pd.Series[float] = train_df["lmp"]
        X_test: pd.DataFrame = test_df[FEATURE_COLS]
        y_test: pd.Series[float] = test_df["lmp"]

        self._model_p10 = _make_quantile_model(0.1)
        self._model_p50 = _make_quantile_model(0.5)
        self._model_p90 = _make_quantile_model(0.9)

        self._model_p10.fit(X_train, y_train)
        self._model_p50.fit(X_train, y_train)
        self._model_p90.fit(X_train, y_train)

        preds_p50: np.ndarray[Any, np.dtype[np.float64]] = self._model_p50.predict(X_test)
        preds_p10: np.ndarray[Any, np.dtype[np.float64]] = self._model_p10.predict(X_test)
        preds_p90: np.ndarray[Any, np.dtype[np.float64]] = self._model_p90.predict(X_test)

        y_arr: np.ndarray[Any, np.dtype[np.float64]] = y_test.to_numpy()
        mae: float = float(mean_absolute_error(y_arr, preds_p50))
        rmse: float = float(math.sqrt(mean_squared_error(y_arr, preds_p50)))
        bias: float = float(np.mean(preds_p50 - y_arr))

        in_interval: np.ndarray[Any, np.dtype[np.bool_]] = (
            (y_arr >= preds_p10) & (y_arr <= preds_p90)
        )
        calibration: float = float(np.mean(in_interval))

        self._metrics = {
            "mae": mae,
            "rmse": rmse,
            "bias": bias,
            "calibration": calibration,
        }
        return {"mae": mae, "rmse": rmse}

    def predict(self, features: pd.DataFrame, horizon: int) -> list[ForecastInterval]:
        if self._model_p10 is None or self._model_p50 is None or self._model_p90 is None:
            raise RuntimeError("Model is not trained. Call train() first.")

        last_row = features.iloc[-1]
        has_time_col = "time" in features.columns
        last_time = (
            pd.Timestamp(last_row["time"]) if has_time_col else pd.Timestamp.now(tz="UTC")
        )
        base_lmp = (
            float(last_row["rolling_mean_24h"]) if "rolling_mean_24h" in features.columns else 35.0
        )

        intervals: list[ForecastInterval] = []

        # Resample 5-min history to hourly so lag indices (1, 2, 4, 24, 168)
        # represent 1h, 2h, 4h, 24h, 7d in the rolling prediction window.
        if "time" in features.columns:
            hourly_lmp = (
                features.set_index("time")["lmp"]
                .resample("1h")
                .mean()
                .dropna()
                .tolist()
            )
        else:
            hourly_lmp = features["lmp"].tolist()
        lag_window: list[float] = hourly_lmp[-2016:]  # up to 84 days

        for h in range(1, horizon + 1):
            future_time = last_time + pd.Timedelta(hours=h)
            hour = float(future_time.hour)
            dow = float(future_time.dayofweek)
            month = float(future_time.month)
            is_weekend = float(dow >= 5)

            lag_1 = lag_window[-1] if len(lag_window) >= 1 else base_lmp
            lag_2 = lag_window[-2] if len(lag_window) >= 2 else base_lmp
            lag_4 = lag_window[-4] if len(lag_window) >= 4 else base_lmp
            lag_24 = lag_window[-24] if len(lag_window) >= 24 else base_lmp
            lag_48 = lag_window[-48] if len(lag_window) >= 48 else lag_24
            lag_168 = lag_window[-168] if len(lag_window) >= 168 else lag_24

            recent_24 = lag_window[-24:] if len(lag_window) >= 24 else lag_window
            rolling_mean = float(np.mean(recent_24)) if recent_24 else base_lmp
            rolling_std = float(np.std(recent_24)) if len(recent_24) > 1 else 0.0

            row_vals = [
                hour, dow, month, is_weekend,
                lag_1, lag_2, lag_4, lag_24, lag_48, lag_168,
                rolling_mean, rolling_std,
            ]
            row_df = pd.DataFrame([row_vals], columns=FEATURE_COLS)

            pred_p50 = float(self._model_p50.predict(row_df)[0])
            pred_p10 = float(self._model_p10.predict(row_df)[0])
            pred_p90 = float(self._model_p90.predict(row_df)[0])

            intervals.append(
                ForecastInterval(
                    timestamp=future_time.isoformat(),
                    mean=pred_p50,
                    p10=pred_p10,
                    p90=pred_p90,
                )
            )
            lag_window.append(pred_p50)

        return intervals

    def save(self, path: str) -> None:
        with open(path, "wb") as f:
            pickle.dump(
                {
                    "model_id": self.model_id,
                    "model_p10": self._model_p10,
                    "model_p50": self._model_p50,
                    "model_p90": self._model_p90,
                    "metrics": self._metrics,
                },
                f,
            )

    @classmethod
    def load(cls, path: str) -> "PriceForecaster":
        with open(path, "rb") as f:
            data: dict[str, Any] = pickle.load(f)  # noqa: S301
        forecaster = cls(model_id=data["model_id"])
        forecaster._model_p10 = data["model_p10"]
        forecaster._model_p50 = data["model_p50"]
        forecaster._model_p90 = data["model_p90"]
        forecaster._metrics = data["metrics"]
        return forecaster
