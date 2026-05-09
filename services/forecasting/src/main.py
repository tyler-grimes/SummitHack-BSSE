from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from typing import Literal

app = FastAPI(title="Forecasting Service", version="0.1.0")

Market = Literal["DA_ENERGY", "RT_ENERGY", "REG_UP", "REG_DOWN", "SPIN", "NONSPIN"]


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


@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/forecast", response_model=list[ForecastResponse])
async def forecast(req: ForecastRequest) -> list[ForecastResponse]:
    # TODO: load model, query TimescaleDB for features, run inference
    raise HTTPException(status_code=501, detail="Not implemented")


@app.post("/confidence", response_model=ConfidenceResponse)
async def confidence(req: ConfidenceRequest) -> ConfidenceResponse:
    # TODO: query model performance metrics from DB
    raise HTTPException(status_code=501, detail="Not implemented")
