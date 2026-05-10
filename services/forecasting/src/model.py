import math
import pickle
from typing import Any

import numpy as np
import pandas as pd
import xgboost as xgb
from sklearn.metrics import mean_absolute_error, mean_squared_error
from sklearn.model_selection import TimeSeriesSplit

from .features import build_features

# Calendar + weather features derived from the TARGET (future) timestamp.
# Weather is treated as a "known-future" exogenous variable — we fetch the
# Open-Meteo forecast for the same horizon when predicting.
_CALENDAR_COLS: tuple[str, ...] = (
    "hour",
    "day_of_week",
    "day_of_year",
    "month",
    "is_weekend",
    "hour_x_weekend",
    "hour_x_month",          # seasonal regime: 4pm July ≠ 4pm January
    # Cyclical encodings for smoother periodicity representation
    "hour_sin",
    "hour_cos",
    "month_sin",
    "month_cos",
    "dow_sin",
    "dow_cos",
    "weather_temp_c",
    "weather_wind_ms",
    "weather_solar_wm2",
    "weather_hdd",
    "weather_cdd",
    # ERCOT grid-state: primary spike predictors
    "wind_actual_mw",        # wind generation level
    "wind_ramp_mw",          # wind generation change — sudden drop → spike
    "solar_actual_mw",       # solar generation level
    "solar_ramp_mw",         # solar evening ramp-down → duck curve price spike
    "load_actual_mw",        # high load → scarcity pricing
    "load_deviation_mw",     # load above forecast = demand surprise
    # Fuel cost signal
    "henry_hub",             # Henry Hub gas spot $/MMBtu — sets marginal cost ~70% of hours
)

# Lag/rolling features derived from the CURRENT (last known) timestamp.
_LAG_COLS: tuple[str, ...] = (
    "lag_1h",
    "lag_2h",
    "lag_4h",
    "lag_24h",
    "lag_48h",
    "lag_72h",
    "lag_168h",
    "rolling_mean_24h",
    "rolling_std_24h",
    "rolling_mean_7d",
    "rolling_std_7d",
)

# horizon is appended last so the model knows how far ahead it's predicting.
FEATURE_COLS: list[str] = list(_CALENDAR_COLS) + list(_LAG_COLS) + ["horizon"]

_TRAIN_SPLIT: float = 0.8
_MAX_HORIZON: int = 24  # hours ahead to generate multi-step training samples
_EARLY_STOPPING_ROUNDS: int = 50
_MAX_ESTIMATORS: int = 1000
_CV_FOLDS: int = 3  # TimeSeriesSplit folds for best n_estimators selection


def _xgb_device() -> str:
    """Return 'cuda' if an NVIDIA GPU is available to XGBoost, else 'cpu'."""
    try:
        import xgboost as _xgb
        import numpy as _np
        _m = _xgb.XGBRegressor(tree_method="hist", device="cuda", n_estimators=1)
        _m.fit(_np.array([[1.0]]), _np.array([1.0]))
        return "cuda"
    except Exception:
        return "cpu"


_DEVICE: str = _xgb_device()


def _make_quantile_model(alpha: float, n_estimators: int = _MAX_ESTIMATORS) -> xgb.XGBRegressor:
    return xgb.XGBRegressor(
        objective="reg:quantileerror",
        quantile_alpha=alpha,
        n_estimators=n_estimators,
        max_depth=5,
        learning_rate=0.03,
        subsample=0.8,
        colsample_bytree=0.8,
        min_child_weight=20,
        # n_jobs is ignored when device='cuda'; set to 1 to avoid thread contention.
        n_jobs=1 if _DEVICE == "cuda" else -1,
        tree_method="hist",
        device=_DEVICE,
        early_stopping_rounds=_EARLY_STOPPING_ROUNDS,
    )


def _cv_best_estimators(X: pd.DataFrame, y: pd.Series, alpha: float) -> int:
    """Use TimeSeriesSplit CV to find the optimal number of boosting rounds.

    Trains with early stopping on each fold and returns the median
    best_iteration across folds, preventing both over- and under-fitting.
    """
    tscv = TimeSeriesSplit(n_splits=_CV_FOLDS)
    best_iters: list[int] = []
    for train_idx, val_idx in tscv.split(X):
        X_tr, X_val = X.iloc[train_idx], X.iloc[val_idx]
        y_tr, y_val = y.iloc[train_idx], y.iloc[val_idx]
        m = _make_quantile_model(alpha)
        m.fit(X_tr, y_tr, eval_set=[(X_val, y_val)], verbose=False)
        best_iters.append(int(m.best_iteration) if m.best_iteration else _MAX_ESTIMATORS)
    return max(50, int(np.median(best_iters)))


def _resample_hourly(df: pd.DataFrame) -> pd.DataFrame:
    return (
        df.assign(time=pd.to_datetime(df["time"], utc=True))
        .set_index("time")["lmp"]
        .resample("1h")
        .mean()
        .dropna()
        .reset_index()
    )


def _build_multistep_matrix(features_h: pd.DataFrame) -> pd.DataFrame:
    """Expand hourly feature rows into (current features, horizon h) -> price at +h rows.

    Each row also carries a ``_src_idx`` column that records the originating
    time-step index so the caller can split on unique timestamps *before*
    expansion, preventing temporal leakage between train and test sets.
    """
    rows: list[dict[str, float]] = []
    n = len(features_h)
    for i in range(n - _MAX_HORIZON):
        current = features_h.iloc[i]
        # Let XGBoost handle NaN natively instead of injecting a magic constant.
        lag_vals = {
            col: float(current[col]) if col in features_h.columns and not pd.isna(current[col]) else float("nan")
            for col in _LAG_COLS
        }
        for h in range(1, _MAX_HORIZON + 1):
            future = features_h.iloc[i + h]
            row: dict[str, float] = {
                col: float(future[col]) for col in _CALENDAR_COLS if col in features_h.columns
            }
            row.update(lag_vals)
            row["horizon"] = float(h)
            row["lmp"] = float(future["lmp"])
            row["_src_idx"] = float(i)
            rows.append(row)
    return pd.DataFrame(rows)


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

    def train(
        self,
        df: pd.DataFrame,
        weather_df: pd.DataFrame | None = None,
        grid_state_df: pd.DataFrame | None = None,
        gas_price_df: pd.DataFrame | None = None,
    ) -> dict[str, float]:
        # Resample raw (possibly 15-min) data to hourly for clean multi-step indexing.
        df_h = _resample_hourly(df)
        features_h = build_features(df_h, weather_df, grid_state_df, gas_price_df)

        if len(features_h) < 100:
            raise ValueError(
                f"Insufficient data for training: {len(features_h)} hourly rows after feature engineering"
            )

        ms_df = _build_multistep_matrix(features_h)

        # Split on unique source-time indices so no temporal leakage occurs
        # between train and test sets (overlapping windows stay on the same side).
        unique_src = sorted(ms_df["_src_idx"].unique())
        split_src = unique_src[int(len(unique_src) * _TRAIN_SPLIT)]
        train_df = ms_df[ms_df["_src_idx"] < split_src].drop(columns=["_src_idx"])
        test_df = ms_df[ms_df["_src_idx"] >= split_src].drop(columns=["_src_idx"])

        X_train: pd.DataFrame = train_df[FEATURE_COLS]
        y_train: pd.Series[float] = train_df["lmp"]
        X_test: pd.DataFrame = test_df[FEATURE_COLS]
        y_test: pd.Series[float] = test_df["lmp"]

        # Clip spike outliers for p50 so the median estimator tracks the base price,
        # not ERCOT's rare $9k/MWh events. p90 still trains on raw data to capture upside.
        spike_cap = float(y_train.quantile(0.99))
        y_train_clipped = y_train.clip(upper=spike_cap)

        # Find optimal boosting rounds per quantile via TimeSeriesSplit CV.
        n_p10 = _cv_best_estimators(X_train, y_train, alpha=0.1)
        n_p50 = _cv_best_estimators(X_train, y_train_clipped, alpha=0.5)
        n_p90 = _cv_best_estimators(X_train, y_train, alpha=0.9)

        # Final models use CV-tuned rounds; no eval_set needed so no data is held out.
        self._model_p10 = _make_quantile_model(0.1, n_estimators=n_p10)
        self._model_p50 = _make_quantile_model(0.5, n_estimators=n_p50)
        self._model_p90 = _make_quantile_model(0.9, n_estimators=n_p90)

        # Remove early_stopping_rounds for the final fit since there's no eval_set.
        for m in (self._model_p10, self._model_p50, self._model_p90):
            m.set_params(early_stopping_rounds=None)

        self._model_p10.fit(X_train, y_train)
        self._model_p50.fit(X_train, y_train_clipped)
        self._model_p90.fit(X_train, y_train)

        preds_p50: np.ndarray[Any, np.dtype[np.float64]] = self._model_p50.predict(X_test)
        preds_p10: np.ndarray[Any, np.dtype[np.float64]] = self._model_p10.predict(X_test)
        preds_p90: np.ndarray[Any, np.dtype[np.float64]] = self._model_p90.predict(X_test)

        y_arr: np.ndarray[Any, np.dtype[np.float64]] = y_test.to_numpy()
        mae: float = float(mean_absolute_error(y_arr, preds_p50))
        rmse: float = float(math.sqrt(mean_squared_error(y_arr, preds_p50)))
        bias: float = float(np.mean(preds_p50 - y_arr))
        in_interval: np.ndarray[Any, np.dtype[np.bool_]] = (y_arr >= preds_p10) & (y_arr <= preds_p90)
        calibration: float = float(np.mean(in_interval))

        self._metrics = {
            "mae": mae,
            "rmse": rmse,
            "bias": bias,
            "calibration": calibration,
        }
        return {"mae": mae, "rmse": rmse}

    def predict(
        self,
        features: pd.DataFrame,
        horizon: int,
        weather_forecast: pd.DataFrame | None = None,
    ) -> list[ForecastInterval]:
        if self._model_p10 is None or self._model_p50 is None or self._model_p90 is None:
            raise RuntimeError("Model is not trained. Call train() first.")

        last_row = features.iloc[-1]
        last_time = (
            pd.Timestamp(last_row["time"]) if "time" in features.columns
            else pd.Timestamp.now(tz="UTC")
        )

        # Extract lag/rolling features from the last known observation.
        # Let XGBoost handle NaN natively instead of injecting a magic constant.
        lag_vals: dict[str, float] = {
            col: (
                float(last_row[col])
                if col in features.columns and not pd.isna(last_row[col])
                else float("nan")
            )
            for col in _LAG_COLS
        }

        # Weather fallback: last known values if forecast unavailable.
        _w_default: dict[str, float] = {
            "weather_temp_c":    float(last_row["weather_temp_c"])    if "weather_temp_c"    in features.columns else 20.0,
            "weather_wind_ms":   float(last_row["weather_wind_ms"])   if "weather_wind_ms"   in features.columns else 3.0,
            "weather_solar_wm2": float(last_row["weather_solar_wm2"]) if "weather_solar_wm2" in features.columns else 0.0,
            "weather_hdd":       float(last_row["weather_hdd"])       if "weather_hdd"       in features.columns else 0.0,
            "weather_cdd":       float(last_row["weather_cdd"])       if "weather_cdd"       in features.columns else 2.0,
        }

        def _gs_val(col: str) -> float:
            """Last known grid-state value; NaN if unavailable (XGBoost handles it)."""
            if col in features.columns and not pd.isna(last_row[col]):
                return float(last_row[col])
            return float("nan")

        _gs_default: dict[str, float] = {
            "wind_actual_mw":    _gs_val("wind_actual_mw"),
            "wind_ramp_mw":      _gs_val("wind_ramp_mw"),
            "solar_actual_mw":   _gs_val("solar_actual_mw"),
            "solar_ramp_mw":     _gs_val("solar_ramp_mw"),
            "load_actual_mw":    _gs_val("load_actual_mw"),
            "load_deviation_mw": _gs_val("load_deviation_mw"),
            "henry_hub":         _gs_val("henry_hub"),
        }

        # Build hour → weather lookup from forecast DataFrame.
        weather_by_hour: dict[pd.Timestamp, dict[str, float]] = {}
        if weather_forecast is not None and not weather_forecast.empty:
            for _, wrow in weather_forecast.iterrows():
                t = pd.Timestamp(wrow["time"]).floor("h")
                temp = float(wrow["temperature_2m"])
                weather_by_hour[t] = {
                    "weather_temp_c":    temp,
                    "weather_wind_ms":   float(wrow["wind_speed_10m"]),
                    "weather_solar_wm2": float(wrow["shortwave_radiation"]),
                    "weather_hdd":       max(0.0, 18.0 - temp),
                    "weather_cdd":       max(0.0, temp - 18.0),
                }

        intervals: list[ForecastInterval] = []
        for h in range(1, horizon + 1):
            future_time = last_time + pd.Timedelta(hours=h)
            future_h = future_time.floor("h")

            hour = float(future_time.hour)
            dow = float(future_time.dayofweek)
            month = float(future_time.month)

            row_dict: dict[str, float] = dict(lag_vals)
            row_dict["hour"] = hour
            row_dict["day_of_week"] = dow
            row_dict["day_of_year"] = float(future_time.timetuple().tm_yday)
            row_dict["month"] = month
            row_dict["is_weekend"] = float(future_time.dayofweek >= 5)
            row_dict["hour_x_weekend"] = float(future_time.hour * (future_time.dayofweek >= 5))
            row_dict["hour_x_month"] = hour * month
            # Cyclical features
            row_dict["hour_sin"] = math.sin(hour * (2.0 * math.pi / 24.0))
            row_dict["hour_cos"] = math.cos(hour * (2.0 * math.pi / 24.0))
            row_dict["month_sin"] = math.sin(month * (2.0 * math.pi / 12.0))
            row_dict["month_cos"] = math.cos(month * (2.0 * math.pi / 12.0))
            row_dict["dow_sin"] = math.sin(dow * (2.0 * math.pi / 7.0))
            row_dict["dow_cos"] = math.cos(dow * (2.0 * math.pi / 7.0))
            row_dict.update(weather_by_hour.get(future_h, _w_default))
            # Grid-state: carry last known values forward (no future grid-state available at predict time)
            row_dict.update(_gs_default)
            row_dict["horizon"] = float(h)

            row_df = pd.DataFrame([row_dict], columns=FEATURE_COLS)
            pred_p50 = float(self._model_p50.predict(row_df)[0])
            pred_p10 = float(self._model_p10.predict(row_df)[0])
            pred_p90 = float(self._model_p90.predict(row_df)[0])

            intervals.append(ForecastInterval(
                timestamp=future_time.isoformat(),
                mean=pred_p50,
                p10=pred_p10,
                p90=pred_p90,
            ))

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
