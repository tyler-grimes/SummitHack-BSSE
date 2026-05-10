import glob
import logging
import os
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from typing import Literal

import pandas as pd
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from .config import settings
from .db import close_pool, fetch_lmp_history, init_pool
from .features import build_features
from .model import ForecastInterval as ModelForecastInterval
from .model import PriceForecaster

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


# ---------------------------------------------------------------------------
# Pydantic models
# ---------------------------------------------------------------------------


class ForecastRequest(BaseModel):
    iso: str
    nodes: list[str]
    market: Market
    horizon_hours: int


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
                df = await fetch_lmp_history(req.iso, node, days=90)
                if df.empty:
                    raise ValueError("No historical data available")
                feature_df = build_features(df)
                model_ivs = forecaster.predict(feature_df, req.horizon_hours)
                intervals = _to_api_intervals(model_ivs)
                confidence = _confidence_from_metrics(forecaster.get_metrics())
            except Exception:
                logger.warning("Model predict failed for %s; falling back to synthetic", mid)
                intervals = _synthetic_forecast(req.horizon_hours)
                confidence = 0.0
        else:
            base = 35.0
            try:
                df = await fetch_lmp_history(req.iso, node, days=7)
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


@app.post("/train", response_model=TrainResponse)
async def train(req: TrainRequest) -> TrainResponse:
    mid = _model_id(req.iso, req.node, req.market)

    df = await fetch_lmp_history(req.iso, req.node, days=90)
    if df.empty:
        raise HTTPException(status_code=422, detail=f"No LMP data found for {mid}")

    forecaster = PriceForecaster(model_id=mid)
    try:
        metrics = forecaster.train(df)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    os.makedirs(settings.model_dir, exist_ok=True)
    forecaster.save(_model_path(mid))
    _models[mid] = forecaster

    feature_df = build_features(df)
    training_rows = len(feature_df)

    return TrainResponse(
        model_id=mid,
        mae=metrics["mae"],
        rmse=metrics["rmse"],
        training_rows=training_rows,
    )
