from typing import Any

import numpy as np
import numpy.typing as npt
from fastapi import FastAPI
from pydantic import BaseModel

from .battery import BatteryParams
from .solver import solve_dispatch
from .state import get_battery_params

app = FastAPI(title="Optimization Service", version="0.1.0")


class OptimizeRequest(BaseModel):
    asset_id: str
    forecasts: dict[str, list[dict[str, Any]]]
    horizon_hours: int
    markets: list[str]


class DispatchInterval(BaseModel):
    timestamp: str
    charge_mw: float
    discharge_mw: float
    market: str
    expected_revenue_dollars: float


class OptimizeResponse(BaseModel):
    asset_id: str
    intervals: list[DispatchInterval]
    total_expected_revenue_dollars: float
    solver_status: str


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/battery/{asset_id}", response_model=BatteryParams)
def get_battery(asset_id: str) -> BatteryParams:
    return get_battery_params(asset_id)


@app.post("/optimize", response_model=OptimizeResponse)
async def optimize(req: OptimizeRequest) -> OptimizeResponse:
    params = get_battery_params(req.asset_id)

    merged: dict[str, dict[str, Any]] = {}
    final_status = "optimal"

    for market in req.markets:
        if market not in req.forecasts:
            continue

        forecast_list = req.forecasts[market]
        prices: npt.NDArray[np.float64] = np.array(
            [float(f["mean"]) for f in forecast_list]
        )
        timestamps = [str(f["timestamp"]) for f in forecast_list]

        status, intervals = solve_dispatch(params, prices, timestamps, market)

        if status not in ("optimal", "optimal_inaccurate"):
            final_status = status

        for interval in intervals:
            ts: str = interval["timestamp"]
            rev: float = float(interval["expected_revenue_dollars"])
            if ts not in merged or rev > float(merged[ts]["expected_revenue_dollars"]):
                merged[ts] = interval

    sorted_intervals = sorted(merged.values(), key=lambda x: str(x["timestamp"]))
    dispatch_intervals = [DispatchInterval(**iv) for iv in sorted_intervals]
    total_revenue = sum(iv.expected_revenue_dollars for iv in dispatch_intervals)

    return OptimizeResponse(
        asset_id=req.asset_id,
        intervals=dispatch_intervals,
        total_expected_revenue_dollars=total_revenue,
        solver_status=final_status,
    )
