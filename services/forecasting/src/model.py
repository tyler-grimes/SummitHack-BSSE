import math
import pickle
from typing import Any

import numpy as np
import pandas as pd
import xgboost as xgb
from sklearn.calibration import CalibratedClassifierCV
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
    # Reserve margin proxies (true capacity data not available in schema)
    "net_load_mw",           # load - wind - solar: thermal residual demand; high → scarcity
    "renewable_penetration", # (wind + solar) / load: sudden drop from high penetration → spike
    # Outage capacity: MW offline constrains thermal headroom → reserve squeeze → spike
    "total_outage_mw",
    "outage_mw_zone_north",
    "outage_mw_zone_south",
    "outage_mw_zone_west",
    "outage_mw_zone_houston",
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
    # Intraday momentum: captures current-day price regime
    "rolling_std_6h",       # short-window volatility — high → spread day
    "lag1h_x_hour",         # price level × time-of-day interaction
    "lmp_momentum_3h",      # 3-hour rate of change — rising prices → afternoon peak
    "intraday_min_so_far",  # cheapest price seen today so far
    "intraday_max_so_far",  # most expensive price seen today so far
    "intraday_spread_so_far",  # today's spread so far — key dispatch signal
)

# horizon is appended last so the model knows how far ahead it's predicting.
FEATURE_COLS: list[str] = list(_CALENDAR_COLS) + list(_LAG_COLS) + ["horizon"]

_TRAIN_SPLIT: float = 0.8
_MAX_HORIZON: int = 24  # hours ahead to generate multi-step training samples
_EARLY_STOPPING_ROUNDS: int = 50
_MAX_ESTIMATORS: int = 1000
_CV_FOLDS: int = 3  # TimeSeriesSplit folds for best n_estimators selection

# Two-model spike architecture constants.
_SPIKE_QUANTILE: float = 0.95
# Below this threshold the base model runs unmodified (no spike contamination).
# Above it: blend weight = max(spike_prob, _SPIKE_BLEND_FLOOR) so even a
# low-confidence spike prediction still gets meaningful weight from the spike
# regressor, directly attacking the negative bias on actual spike hours.
_SPIKE_BLEND_THRESHOLD: float = 0.20
_SPIKE_BLEND_FLOOR: float = 0.40
# Fraction of training data held out for isotonic calibration of the classifier.
# Must not overlap with the test set (which comes from the outer _TRAIN_SPLIT).
_CALIBRATION_SPLIT: float = 0.8


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


def _make_classifier(n_estimators: int = _MAX_ESTIMATORS) -> xgb.XGBClassifier:
    """Binary classifier: P(price is a spike hour)."""
    return xgb.XGBClassifier(
        objective="binary:logistic",
        eval_metric="logloss",
        n_estimators=n_estimators,
        max_depth=5,
        learning_rate=0.03,
        subsample=0.8,
        colsample_bytree=0.8,
        min_child_weight=10,
        scale_pos_weight=6,  # mild upweight; isotonic calibration corrects residual bias
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


def _cv_best_estimators_classifier(X: pd.DataFrame, y: pd.Series) -> int:
    """TimeSeriesSplit CV for the spike binary classifier."""
    tscv = TimeSeriesSplit(n_splits=_CV_FOLDS)
    best_iters: list[int] = []
    for train_idx, val_idx in tscv.split(X):
        X_tr, X_val = X.iloc[train_idx], X.iloc[val_idx]
        y_tr, y_val = y.iloc[train_idx], y.iloc[val_idx]
        m = _make_classifier()
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
        # Base quantile models — trained on non-spike hours (lmp ≤ p95)
        self._model_p10: xgb.XGBRegressor | None = None
        self._model_p50: xgb.XGBRegressor | None = None
        self._model_p90: xgb.XGBRegressor | None = None
        # Spike classifier — trained on all hours; predicts P(spike)
        self._classifier: xgb.XGBClassifier | None = None
        # Isotonic-calibrated wrapper; used for blending at predict time
        self._calibrated_classifier: CalibratedClassifierCV | None = None
        # Spike regressor — trained on spike hours only (lmp > p95)
        self._spike_p10: xgb.XGBRegressor | None = None
        self._spike_p50: xgb.XGBRegressor | None = None
        self._spike_p90: xgb.XGBRegressor | None = None
        # Spike threshold (p95 of training LMP)
        self._spike_threshold: float = 80.0
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
        outage_df: pd.DataFrame | None = None,
    ) -> dict[str, float]:
        # Resample raw (possibly 15-min) data to hourly for clean multi-step indexing.
        df_h = _resample_hourly(df)
        features_h = build_features(df_h, weather_df, grid_state_df, gas_price_df, outage_df)

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
        y_train: pd.Series = train_df["lmp"]
        X_test: pd.DataFrame = test_df[FEATURE_COLS]
        y_test: pd.Series = test_df["lmp"]

        # ── Spike threshold (computed on training set only — no leakage) ──────────
        self._spike_threshold = float(y_train.quantile(_SPIKE_QUANTILE))
        is_spike_train = y_train > self._spike_threshold
        is_spike_test = y_test > self._spike_threshold

        # ── Base models: trained on non-spike hours ───────────────────────────────
        base_mask = ~is_spike_train
        X_base, y_base = X_train[base_mask], y_train[base_mask]

        # Clip p50 outliers within the base set for a cleaner median fit.
        spike_cap = float(y_base.quantile(0.99))
        y_base_clipped = y_base.clip(upper=spike_cap)

        n_p10 = _cv_best_estimators(X_base, y_base, alpha=0.1)
        n_p50 = _cv_best_estimators(X_base, y_base_clipped, alpha=0.5)
        n_p90 = _cv_best_estimators(X_base, y_base, alpha=0.9)

        self._model_p10 = _make_quantile_model(0.1, n_estimators=n_p10)
        self._model_p50 = _make_quantile_model(0.5, n_estimators=n_p50)
        self._model_p90 = _make_quantile_model(0.9, n_estimators=n_p90)
        for m in (self._model_p10, self._model_p50, self._model_p90):
            m.set_params(early_stopping_rounds=None)
        self._model_p10.fit(X_base, y_base)
        self._model_p50.fit(X_base, y_base_clipped)
        self._model_p90.fit(X_base, y_base)

        # ── Spike classifier: trained on first 80% of training data ──────────────
        # The remaining 20% is a held-out calibration set used to fit isotonic
        # regression on top of the raw XGBoost probabilities.  This split is
        # strictly temporal (no shuffle) to avoid leakage.
        y_clf = is_spike_train.astype(int)
        cal_cutoff = int(len(X_train) * _CALIBRATION_SPLIT)
        X_clf_tr, X_clf_cal = X_train.iloc[:cal_cutoff], X_train.iloc[cal_cutoff:]
        y_clf_tr, y_clf_cal = y_clf.iloc[:cal_cutoff], y_clf.iloc[cal_cutoff:]

        n_clf = _cv_best_estimators_classifier(X_clf_tr, y_clf_tr)
        self._classifier = _make_classifier(n_estimators=n_clf)
        self._classifier.set_params(early_stopping_rounds=None)
        self._classifier.fit(X_clf_tr, y_clf_tr)

        self._calibrated_classifier = CalibratedClassifierCV(
            self._classifier, method="isotonic", cv="prefit"
        )
        self._calibrated_classifier.fit(X_clf_cal, y_clf_cal)

        # ── Spike regressor: trained on spike hours only ──────────────────────────
        spike_mask = is_spike_train
        X_spike, y_spike = X_train[spike_mask], y_train[spike_mask]

        if len(X_spike) >= 50:
            n_sp10 = _cv_best_estimators(X_spike, y_spike, alpha=0.1)
            n_sp50 = _cv_best_estimators(X_spike, y_spike, alpha=0.5)
            n_sp90 = _cv_best_estimators(X_spike, y_spike, alpha=0.9)

            self._spike_p10 = _make_quantile_model(0.1, n_estimators=n_sp10)
            self._spike_p50 = _make_quantile_model(0.5, n_estimators=n_sp50)
            self._spike_p90 = _make_quantile_model(0.9, n_estimators=n_sp90)
            for m in (self._spike_p10, self._spike_p50, self._spike_p90):
                m.set_params(early_stopping_rounds=None)
            self._spike_p10.fit(X_spike, y_spike)
            self._spike_p50.fit(X_spike, y_spike)
            self._spike_p90.fit(X_spike, y_spike)
        else:
            # Insufficient spike samples — fall back to base models.
            self._spike_p10 = self._model_p10
            self._spike_p50 = self._model_p50
            self._spike_p90 = self._model_p90

        # ── Evaluate on full test set (continuous probability blend) ─────────────
        # Use calibrated probabilities so normal hours are not contaminated by
        # an over-aggressive classifier.
        spike_probs: np.ndarray = self._calibrated_classifier.predict_proba(X_test)[:, 1]

        base_p50 = self._model_p50.predict(X_test)
        base_p10 = self._model_p10.predict(X_test)
        base_p90 = self._model_p90.predict(X_test)

        spike_p50 = self._spike_p50.predict(X_test)
        spike_p10 = self._spike_p10.predict(X_test)
        spike_p90 = self._spike_p90.predict(X_test)

        # Below threshold: pure base (no spike contamination on normal hours).
        # Above threshold: blend weight = max(prob, floor) so true spike hours
        # always get at least _SPIKE_BLEND_FLOOR weight from the spike regressor.
        above = spike_probs >= _SPIKE_BLEND_THRESHOLD
        weights = np.where(above, np.maximum(spike_probs, _SPIKE_BLEND_FLOOR), 0.0)
        preds_p50 = weights * spike_p50 + (1 - weights) * base_p50
        preds_p10 = weights * spike_p10 + (1 - weights) * base_p10
        preds_p90 = weights * spike_p90 + (1 - weights) * base_p90

        # use_spike at threshold for recall/precision diagnostics only.
        use_spike: np.ndarray = above

        y_arr: np.ndarray = y_test.to_numpy()
        mae: float = float(mean_absolute_error(y_arr, preds_p50))
        rmse: float = float(math.sqrt(mean_squared_error(y_arr, preds_p50)))
        bias: float = float(np.mean(preds_p50 - y_arr))
        in_interval: np.ndarray = (y_arr >= preds_p10) & (y_arr <= preds_p90)
        calibration: float = float(np.mean(in_interval))

        # Spike-hour breakdown for diagnostics.
        spike_arr = is_spike_test.to_numpy()
        spike_mae: float = float(mean_absolute_error(y_arr[spike_arr], preds_p50[spike_arr])) if spike_arr.any() else float("nan")
        spike_rmse: float = float(math.sqrt(mean_squared_error(y_arr[spike_arr], preds_p50[spike_arr]))) if spike_arr.any() else float("nan")
        spike_recall = float(np.mean(use_spike[spike_arr])) if spike_arr.any() else float("nan")
        spike_precision = float(np.mean(spike_arr[use_spike])) if use_spike.any() else float("nan")

        self._metrics = {
            "mae": mae,
            "rmse": rmse,
            "bias": bias,
            "calibration": calibration,
            "spike_threshold": self._spike_threshold,
            "spike_mae": spike_mae,
            "spike_rmse": spike_rmse,
            "spike_recall": spike_recall,
            "spike_precision": spike_precision,
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
        lag_vals: dict[str, float] = {
            col: (
                float(last_row[col])
                if col in features.columns and not pd.isna(last_row[col])
                else float("nan")
            )
            for col in _LAG_COLS
        }

        # Intraday features that aren't in _LAG_COLS by default but need
        # explicit computation at predict time if the columns are missing.
        # (They're included in _LAG_COLS already — this just ensures non-NaN
        # values when predicting on a fresh features DataFrame that lacks them.)
        _intraday_defaults = {
            "rolling_std_6h": 0.0,
            "lag1h_x_hour": float("nan"),
            "lmp_momentum_3h": 0.0,
            "intraday_min_so_far": float("nan"),
            "intraday_max_so_far": float("nan"),
            "intraday_spread_so_far": 0.0,
        }
        for k, default in _intraday_defaults.items():
            if k not in lag_vals or pd.isna(lag_vals.get(k, float("nan"))):
                lag_vals[k] = default

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

        _wind = _gs_val("wind_actual_mw")
        _solar = _gs_val("solar_actual_mw")
        _load = _gs_val("load_actual_mw")
        _gs_default: dict[str, float] = {
            "wind_actual_mw":       _wind,
            "wind_ramp_mw":         _gs_val("wind_ramp_mw"),
            "solar_actual_mw":      _solar,
            "solar_ramp_mw":        _gs_val("solar_ramp_mw"),
            "load_actual_mw":       _load,
            "load_deviation_mw":    _gs_val("load_deviation_mw"),
            "henry_hub":            _gs_val("henry_hub"),
            "net_load_mw": (
                _load - _wind - _solar
                if not any(math.isnan(v) for v in (_load, _wind, _solar))
                else float("nan")
            ),
            "renewable_penetration": (
                (_wind + _solar) / _load
                if not any(math.isnan(v) for v in (_load, _wind, _solar)) and _load != 0
                else float("nan")
            ),
            # Outage capacity — carry last known values forward at predict time.
            "total_outage_mw":        _gs_val("total_outage_mw"),
            "outage_mw_zone_north":   _gs_val("outage_mw_zone_north"),
            "outage_mw_zone_south":   _gs_val("outage_mw_zone_south"),
            "outage_mw_zone_west":    _gs_val("outage_mw_zone_west"),
            "outage_mw_zone_houston": _gs_val("outage_mw_zone_houston"),
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
            # Re-compute lag1h_x_hour with the future hour (lag_1h stays = last known price)
            if not pd.isna(lag_vals.get("lag_1h", float("nan"))):
                row_dict["lag1h_x_hour"] = lag_vals["lag_1h"] * hour
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

            base_p50 = float(self._model_p50.predict(row_df)[0])
            base_p10 = float(self._model_p10.predict(row_df)[0])
            base_p90 = float(self._model_p90.predict(row_df)[0])

            # Below threshold: pure base. Above: weight = max(prob, floor).
            clf = self._calibrated_classifier if self._calibrated_classifier is not None else self._classifier
            if clf is not None and self._spike_p50 is not None:
                spike_prob = float(clf.predict_proba(row_df)[0, 1])
                if spike_prob >= _SPIKE_BLEND_THRESHOLD:
                    w = max(spike_prob, _SPIKE_BLEND_FLOOR)
                    pred_p50 = w * float(self._spike_p50.predict(row_df)[0]) + (1 - w) * base_p50
                    pred_p10 = w * float(self._spike_p10.predict(row_df)[0]) + (1 - w) * base_p10  # type: ignore[union-attr]
                    pred_p90 = w * float(self._spike_p90.predict(row_df)[0]) + (1 - w) * base_p90  # type: ignore[union-attr]
                else:
                    pred_p50, pred_p10, pred_p90 = base_p50, base_p10, base_p90
            else:
                pred_p50, pred_p10, pred_p90 = base_p50, base_p10, base_p90

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
                    "classifier": self._classifier,
                    "calibrated_classifier": self._calibrated_classifier,
                    "spike_p10": self._spike_p10,
                    "spike_p50": self._spike_p50,
                    "spike_p90": self._spike_p90,
                    "spike_threshold": self._spike_threshold,
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
        forecaster._classifier = data.get("classifier")
        forecaster._calibrated_classifier = data.get("calibrated_classifier")
        forecaster._spike_p10 = data.get("spike_p10")
        forecaster._spike_p50 = data.get("spike_p50")
        forecaster._spike_p90 = data.get("spike_p90")
        forecaster._spike_threshold = data.get("spike_threshold", 80.0)
        forecaster._metrics = data["metrics"]
        return forecaster
