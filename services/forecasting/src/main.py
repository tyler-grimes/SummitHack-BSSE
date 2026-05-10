import asyncio
import glob
import logging
import os
from collections.abc import AsyncGenerator, Coroutine
from contextlib import asynccontextmanager
from typing import Any, Literal

import pandas as pd
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from .config import settings
from .db import close_pool, fetch_gas_prices, fetch_grid_state, fetch_lmp_history, fetch_outage_capacity, init_pool
from .features import build_features
from .model import ForecastInterval as ModelForecastInterval
from .model import PriceForecaster
from .weather import fetch_weather_forecast, fetch_weather_history, get_node_location

logger = logging.getLogger(__name__)

Market = Literal["DA_ENERGY", "RT_ENERGY", "REG_UP", "REG_DOWN", "SPIN", "NONSPIN"]

# In-memory registry: model_id -> PriceForecaster
_models: dict[str, PriceForecaster] = {}


def _model_id(iso: str, node: str, market: str) -> str:
    return f"{iso}_{node}_{market}"


def _model_path(model_id: str) -> str:
    return os.path.join(settings.model_dir, f"{model_id}.pkl")


def _load_models_from_disk() -> None:
    os.makedirs(settings.model_dir, exist_ok=True)
    pattern = os.path.join(settings.model_dir, "*.pkl")
    for pkl_path in glob.glob(pattern):
        try:
            forecaster = PriceForecaster.load(pkl_path)
            _models[forecaster.model_id] = forecaster
            logger.info("Loaded model %s from %s", forecaster.model_id, pkl_path)
        except Exception:
            logger.exception("Failed to load model from %s", pkl_path)


@asynccontextmanager
async def _lifespan(_app: FastAPI) -> AsyncGenerator[None, None]:
    try:
        await init_pool()
        logger.info("Database pool initialized")
    except Exception:
        logger.warning("Database pool initialization failed; continuing without DB")
    _load_models_from_disk()
    yield
    await close_pool()


app = FastAPI(title="Forecasting Service", version="0.1.0", lifespan=_lifespan)


async def _gather(*coros: Coroutine[Any, Any, Any]) -> tuple[Any, ...]:
    return tuple(await asyncio.gather(*coros))


# ---------------------------------------------------------------------------
# Pydantic models
# ---------------------------------------------------------------------------


class ForecastRequest(BaseModel):
    iso: str
    nodes: list[str]
    market: Market
    horizon_hours: int
    as_of_date: str | None = None  # ISO date string; limits history to data on/before this date


class ForecastInterval(BaseModel):
    timestamp: str
    mean: float
    p10: float
    p90: float


class ForecastResponse(BaseModel):
    iso: str
    node: str
    market: str
    intervals: list[ForecastInterval]
    model_id: str
    confidence: float


class ConfidenceRequest(BaseModel):
    model_id: str
    recent_days: int = 7


class ConfidenceResponse(BaseModel):
    model_id: str
    mae: float
    rmse: float
    bias: float
    calibration: float
    sample_size: int


class TrainRequest(BaseModel):
    iso: str
    node: str
    market: Market


class TrainResponse(BaseModel):
    model_id: str
    mae: float
    rmse: float
    training_rows: int


# ---------------------------------------------------------------------------
# Synthetic fallback helpers
# ---------------------------------------------------------------------------

_HOURLY_SHAPE: list[float] = [
    20.0, 18.0, 17.0, 16.0, 17.0, 19.0,
    25.0, 30.0, 35.0, 38.0, 40.0, 42.0,
    43.0, 44.0, 45.0, 50.0, 55.0, 58.0,
    54.0, 48.0, 42.0, 38.0, 32.0, 25.0,
]


def _synthetic_forecast(
    horizon: int,
    base_price: float = 35.0,
) -> list[ForecastInterval]:
    now = pd.Timestamp.now(tz="UTC").floor("h")
    shape_mean = sum(_HOURLY_SHAPE) / len(_HOURLY_SHAPE)
    scale = base_price / shape_mean

    result: list[ForecastInterval] = []
    for h in range(1, horizon + 1):
        future = now + pd.Timedelta(hours=h)
        mean = _HOURLY_SHAPE[future.hour] * scale
        result.append(
            ForecastInterval(
                timestamp=future.isoformat(),
                mean=round(mean, 2),
                p10=round(max(0.0, mean - 15.0), 2),
                p90=round(mean + 15.0, 2),
            )
        )
    return result


def _to_api_intervals(model_intervals: list[ModelForecastInterval]) -> list[ForecastInterval]:
    return [
        ForecastInterval(
            timestamp=iv.timestamp,
            mean=round(iv.mean, 2),
            p10=round(iv.p10, 2),
            p90=round(iv.p90, 2),
        )
        for iv in model_intervals
    ]


def _confidence_from_metrics(metrics: dict[str, float]) -> float:
    mae = metrics.get("mae", 0.0)
    calibration = metrics.get("calibration", 0.0)
    mae_score = max(0.0, 1.0 - mae / 100.0)
    return round((mae_score + calibration) / 2.0, 4)


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/forecast", response_model=list[ForecastResponse])
async def forecast(req: ForecastRequest) -> list[ForecastResponse]:
    results: list[ForecastResponse] = []

    for node in req.nodes:
        mid = _model_id(req.iso, node, req.market)
        forecaster = _models.get(mid)

        if forecaster is not None and forecaster.is_trained:
            try:
                df, grid_state_df, gas_price_df = await asyncio.gather(
                    fetch_lmp_history(req.iso, node, days=90, as_of_date=req.as_of_date),
                    fetch_grid_state(days=90, as_of_date=req.as_of_date),
                    fetch_gas_prices(days=90, as_of_date=req.as_of_date),
                )
                if df.empty:
                    raise ValueError("No historical data available")

                grid_state_df = grid_state_df if not grid_state_df.empty else None
                gas_price_df  = gas_price_df  if not gas_price_df.empty  else None

                loc = get_node_location(req.iso, node)
                weather_hist = None
                weather_fc = None
                if loc:
                    lat, lon = loc
                    try:
                        start = df["time"].min()
                        end = df["time"].max()
                        start_str = (start.strftime("%Y-%m-%d") if hasattr(start, "strftime")
                                     else str(start)[:10])
                        end_str = (end.strftime("%Y-%m-%d") if hasattr(end, "strftime")
                                   else str(end)[:10])

                        if req.as_of_date:
                            # Backtesting: the "forecast" horizon is a past date — use the
                            # historical archive so weather features match training distribution.
                            from datetime import date as _date, timedelta
                            sim_day = _date.fromisoformat(req.as_of_date)
                            fc_end = sim_day + timedelta(days=1)
                            weather_hist, weather_fc = await _gather(
                                fetch_weather_history(lat, lon, start_str, end_str),
                                fetch_weather_history(lat, lon, req.as_of_date, str(fc_end)),
                            )
                        else:
                            # Live: fetch actual weather forecast.
                            weather_hist, weather_fc = await _gather(
                                fetch_weather_history(lat, lon, start_str, end_str),
                                fetch_weather_forecast(lat, lon, hours=req.horizon_hours),
                            )
                    except Exception:
                        logger.warning("Weather fetch failed for %s/%s; predicting without weather", req.iso, node)

                feature_df = build_features(df, weather_hist, grid_state_df, gas_price_df)
                model_ivs = forecaster.predict(feature_df, req.horizon_hours, weather_fc)
                intervals = _to_api_intervals(model_ivs)
                confidence = _confidence_from_metrics(forecaster.get_metrics())
            except Exception:
                logger.warning("Model predict failed for %s; falling back to synthetic", mid)
                intervals = _synthetic_forecast(req.horizon_hours)
                confidence = 0.0
        else:
            base = 35.0
            try:
                df = await fetch_lmp_history(req.iso, node, days=7, as_of_date=req.as_of_date)
                if not df.empty:
                    base = float(df["lmp"].mean())
            except Exception:
                logger.debug("DB unavailable; using flat base price for %s", mid)

            intervals = _synthetic_forecast(req.horizon_hours, base_price=base)
            confidence = 0.0

        results.append(
            ForecastResponse(
                iso=req.iso,
                node=node,
                market=req.market,
                intervals=intervals,
                model_id=mid,
                confidence=confidence,
            )
        )

    return results


@app.get("/metrics")
async def metrics(iso: str, node: str, market: str) -> dict[str, float]:
    mid = _model_id(iso, node, market)
    forecaster = _models.get(mid)
    if forecaster is None or not forecaster.is_trained:
        raise HTTPException(status_code=404, detail=f"No trained model for {mid}")
    return forecaster.get_metrics()


@app.post("/confidence", response_model=ConfidenceResponse)
async def confidence(req: ConfidenceRequest) -> ConfidenceResponse:
    forecaster = _models.get(req.model_id)
    if forecaster is None or not forecaster.is_trained:
        return ConfidenceResponse(
            model_id=req.model_id,
            mae=0.0,
            rmse=0.0,
            bias=0.0,
            calibration=0.0,
            sample_size=0,
        )

    metrics = forecaster.get_metrics()
    return ConfidenceResponse(
        model_id=req.model_id,
        mae=metrics.get("mae", 0.0),
        rmse=metrics.get("rmse", 0.0),
        bias=metrics.get("bias", 0.0),
        calibration=metrics.get("calibration", 0.0),
        sample_size=0,
    )


@app.post("/lmp-raw", response_model=list[ForecastResponse])
async def lmp_raw(req: ForecastRequest) -> list[ForecastResponse]:
    """Return actual LMP prices from the DB, shifted to the next 24h window.
    Falls back to the synthetic daily shape when the DB has no data."""
    results: list[ForecastResponse] = []
    for node in req.nodes:
        df = await fetch_lmp_history(req.iso, node, days=7, as_of_date=req.as_of_date)
        now = pd.Timestamp.now(tz="UTC").floor("h")
        if not df.empty:
            df = df.tail(req.horizon_hours).reset_index(drop=True)
            intervals = [
                ForecastInterval(
                    timestamp=(now + pd.Timedelta(hours=i + 1)).isoformat(),
                    mean=round(float(row["lmp"]), 2),
                    p10=round(max(0.0, float(row["lmp"]) * 0.85), 2),
                    p90=round(float(row["lmp"]) * 1.15, 2),
                )
                for i, row in df.iterrows()
            ]
        else:
            shape = _HOURLY_SHAPE
            intervals = [
                ForecastInterval(
                    timestamp=(now + pd.Timedelta(hours=i + 1)).isoformat(),
                    mean=round(shape[i % len(shape)], 2),
                    p10=round(max(0.0, shape[i % len(shape)] - 10.0), 2),
                    p90=round(shape[i % len(shape)] + 10.0, 2),
                )
                for i in range(req.horizon_hours)
            ]
        results.append(ForecastResponse(
            iso=req.iso,
            node=node,
            market=req.market,
            intervals=intervals,
            model_id=f"{req.iso}_{node}_{req.market}_raw",
            confidence=1.0,
        ))
    return results


@app.post("/train", response_model=TrainResponse)
async def train(req: TrainRequest) -> TrainResponse:
    mid = _model_id(req.iso, req.node, req.market)

    # Use full available history (~6 years) so seasonal patterns are well-represented.
    df, grid_state_df, gas_price_df, outage_df = await asyncio.gather(
        fetch_lmp_history(req.iso, req.node, days=2190),
        fetch_grid_state(days=2190),
        fetch_gas_prices(days=2190),
        fetch_outage_capacity(days=2190),
    )
    if df.empty:
        raise HTTPException(status_code=422, detail=f"No LMP data found for {mid}")

    grid_state_df = grid_state_df if not grid_state_df.empty else None
    gas_price_df  = gas_price_df  if not gas_price_df.empty  else None
    outage_df     = outage_df     if not outage_df.empty     else None

    if grid_state_df is not None:
        logger.info("Grid-state rows: %d", len(grid_state_df))
    else:
        logger.warning("No grid-state data; training without wind/solar/load features")
    if gas_price_df is not None:
        logger.info("Gas price rows: %d", len(gas_price_df))
    else:
        logger.warning("No gas price data; training without Henry Hub feature")
    if outage_df is not None:
        logger.info("Outage capacity rows: %d", len(outage_df))
    else:
        logger.warning("No outage capacity data; training without outage features")

    weather_df = None
    loc = get_node_location(req.iso, req.node)
    if loc:
        lat, lon = loc
        try:
            start_str = str(df["time"].min())[:10]
            end_str = str(df["time"].max())[:10]
            weather_df = await fetch_weather_history(lat, lon, start_str, end_str)
            logger.info("Fetched weather for %s/%s: %d rows", req.iso, req.node, len(weather_df))
        except Exception:
            logger.warning("Weather fetch failed for %s/%s; training without weather", req.iso, req.node)

    forecaster = PriceForecaster(model_id=mid)
    try:
        # XGBoost training is CPU-bound — run in a thread to avoid blocking
        # the async event loop and starving other endpoints.
        metrics = await asyncio.to_thread(forecaster.train, df, weather_df, grid_state_df, gas_price_df, outage_df)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    os.makedirs(settings.model_dir, exist_ok=True)
    forecaster.save(_model_path(mid))
    _models[mid] = forecaster

    feature_df = build_features(df, weather_df, grid_state_df, gas_price_df)
    training_rows = len(feature_df)

    return TrainResponse(
        model_id=mid,
        mae=metrics["mae"],
        rmse=metrics["rmse"],
        training_rows=training_rows,
    )
