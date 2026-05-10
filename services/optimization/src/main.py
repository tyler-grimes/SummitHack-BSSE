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
    current_soc_pct: float | None = None  # override initial SoC for the solver


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
def optimize(req: OptimizeRequest) -> OptimizeResponse:
    """Solve dispatch for each market independently and select the market whose
    complete solution yields the highest total revenue.  This guarantees a
    physically consistent SoC trajectory (unlike the previous per-interval
    cherry-pick across markets)."""
    params = get_battery_params(req.asset_id)
    if req.current_soc_pct is not None:
        params = params.model_copy(update={"initial_soc_pct": req.current_soc_pct})

    best_intervals: list[dict[str, Any]] = []
    best_revenue: float = -float("inf")
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
            continue

        market_revenue = sum(float(iv["expected_revenue_dollars"]) for iv in intervals)
        if market_revenue > best_revenue:
            best_revenue = market_revenue
            best_intervals = intervals

    sorted_intervals = sorted(best_intervals, key=lambda x: str(x["timestamp"]))
    dispatch_intervals = [DispatchInterval(**iv) for iv in sorted_intervals]
    total_revenue = sum(iv.expected_revenue_dollars for iv in dispatch_intervals)

    return OptimizeResponse(
        asset_id=req.asset_id,
        intervals=dispatch_intervals,
        total_expected_revenue_dollars=total_revenue,
        solver_status=final_status,
    )
