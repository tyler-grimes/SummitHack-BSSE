import asyncio
from typing import Any

import httpx
import numpy as np
import numpy.typing as npt
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

from .battery import BatteryParams
from .config import FORECASTING_SERVICE_URL
from .dispatch import BatteryDispatchOptimizer, DispatchSchedule
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
        # Use mean prices for the LP objective.  When p10/p90 are available,
        # also solve with an "optimistic" price vector (p90 for discharge,
        # p10 for charge) and keep whichever solution earns more on mean prices.
        # This unlocks dispatch on days where the model is uncertain but the
        # actual spread is profitable.
        mean_prices: npt.NDArray[np.float64] = np.array(
            [float(f["mean"]) for f in forecast_list]
        )
        timestamps = [str(f["timestamp"]) for f in forecast_list]

        status, intervals = solve_dispatch(params, mean_prices, timestamps, market)

        # Optimistic solve: use p90 as discharge price, p10 as charge price
        has_intervals = all("p10" in f and "p90" in f for f in forecast_list)
        if has_intervals:
            p10_prices: npt.NDArray[np.float64] = np.array(
                [float(f["p10"]) for f in forecast_list]
            )
            p90_prices: npt.NDArray[np.float64] = np.array(
                [float(f["p90"]) for f in forecast_list]
            )
            # Optimistic price: for each hour use p90 (best case discharge) or
            # p10 (best case charge) — the LP will allocate correctly.
            optimistic_prices = (p90_prices + p10_prices) / 2.0
            opt_status, opt_intervals = solve_dispatch(
                params, optimistic_prices, timestamps, market
            )
            if opt_status in ("optimal", "optimal_inaccurate"):
                # Evaluate both solutions on mean prices to pick the better one
                mean_rev = sum(float(iv["expected_revenue_dollars"]) for iv in intervals)
                # Re-score optimistic intervals using mean prices
                opt_mean_rev = sum(
                    float(iv["discharge_mw"]) * float(mean_prices[i]) * params.eta_discharge
                    - float(iv["charge_mw"]) * float(mean_prices[i]) / params.eta_charge
                    - params.degradation_per_mwh * (float(iv["charge_mw"]) + float(iv["discharge_mw"]))
                    for i, iv in enumerate(opt_intervals)
                )
                if opt_mean_rev > mean_rev:
                    intervals = opt_intervals

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


# ---------------------------------------------------------------------------
# /dispatch — PuLP-based endpoint
# ---------------------------------------------------------------------------


class BatteryParamsInput(BaseModel):
    capacity_mwh: float = Field(default=100.0, gt=0)
    max_charge_mw: float = Field(default=25.0, gt=0)
    max_discharge_mw: float = Field(default=25.0, gt=0)
    eta_charge: float = Field(default=1.0, gt=0, le=1.0)
    eta_discharge: float = Field(default=1.0, gt=0, le=1.0)
    soc_min_frac: float = Field(default=0.10, ge=0, lt=1.0)
    soc_max_frac: float = Field(default=0.90, gt=0, le=1.0)
    degradation_per_mwh: float = Field(default=0.0, ge=0)


class DispatchRequest(BaseModel):
    hub: str                          # e.g. "HB_NORTH"
    iso: str = "ERCOT"
    market: str = "DA_ENERGY"
    current_soc_frac: float = Field(default=0.50, ge=0, le=1.0)
    horizon_hours: int = Field(default=24, ge=1, le=24)
    battery: BatteryParamsInput = BatteryParamsInput()
    use_raw_lmp: bool = False         # bypass ML forecast, use actual DB prices


class HourlySlot(BaseModel):
    hour: int
    timestamp: str
    net_mw: float          # positive = discharging, negative = charging
    soc_mwh: float
    forecast_price: float
    forecast_revenue: float


class DispatchResponse(BaseModel):
    hub: str
    iso: str
    market: str
    solver_status: str
    initial_soc_mwh: float
    final_soc_mwh: float
    total_forecast_revenue: float
    schedule: list[HourlySlot]


@app.post("/dispatch", response_model=DispatchResponse)
async def dispatch(req: DispatchRequest) -> DispatchResponse:
    """Fetch forecast from the forecasting service and solve dispatch via PuLP LP.

    Pipeline:
      1. Fetch 24h p10/p50/p90 forecast from forecasting service.
      2. Fetch model confidence score.
      3. Build uncertainty-adjusted price vector: low confidence → shade p50
         toward conservative quantile to avoid over-committing on uncertain hours.
      4. Run PuLP LP on adjusted prices.
      5. Return signed net_mw schedule + SoC trajectory.
    """
    model_id = f"{req.iso}_{req.hub}_{req.market}"
    forecast_endpoint = "lmp-raw" if req.use_raw_lmp else "forecast"
    forecast_payload = {
        "iso": req.iso,
        "nodes": [req.hub],
        "market": req.market,
        "horizon_hours": req.horizon_hours,
    }
    confidence_payload = {"model_id": model_id}

    async with httpx.AsyncClient(timeout=30.0) as client:
        try:
            forecast_resp, confidence_resp = await asyncio.gather(
                client.post(f"{FORECASTING_SERVICE_URL}/{forecast_endpoint}", json=forecast_payload),
                client.post(f"{FORECASTING_SERVICE_URL}/confidence", json=confidence_payload),
            )
            forecast_resp.raise_for_status()
        except httpx.HTTPError as exc:
            raise HTTPException(status_code=502, detail=f"Forecasting service error: {exc}") from exc

    forecast_data = forecast_resp.json()
    if not forecast_data:
        raise HTTPException(status_code=502, detail="Empty forecast response")

    node_forecast = forecast_data[0]
    intervals = node_forecast.get("intervals", [])
    if not intervals:
        raise HTTPException(status_code=422, detail="No forecast intervals returned")

    p10 = [float(iv["p10"]) for iv in intervals]
    p50 = [float(iv["mean"]) for iv in intervals]
    p90 = [float(iv["p90"]) for iv in intervals]
    timestamps = [str(iv["timestamp"]) for iv in intervals]

    # Extract confidence (0-1); default 1.0 (trust p50 fully) if unavailable
    confidence = 1.0
    if confidence_resp.is_success:
        conf_data = confidence_resp.json()
        confidence = float(conf_data.get("calibration", 1.0))

    # Build optimizer
    bp = req.battery
    optimizer = BatteryDispatchOptimizer(
        capacity_mwh=bp.capacity_mwh,
        max_charge_mw=bp.max_charge_mw,
        max_discharge_mw=bp.max_discharge_mw,
        eta_charge=bp.eta_charge,
        eta_discharge=bp.eta_discharge,
        soc_min_frac=bp.soc_min_frac,
        soc_max_frac=bp.soc_max_frac,
        initial_soc_frac=req.current_soc_frac,
        degradation_per_mwh=bp.degradation_per_mwh,
    )

    # Uncertainty-adjusted prices: conservative when model is uncertain
    adjusted_prices = optimizer.uncertainty_adjusted_prices(p10, p50, p90, confidence)

    schedule: DispatchSchedule = optimizer.solve(forecast_prices=adjusted_prices)

    hourly: list[HourlySlot] = []
    for h, (net, ts, price) in enumerate(zip(schedule.net_mw, timestamps, adjusted_prices)):
        discharge = max(0.0, net)
        charge = max(0.0, -net)
        slot_revenue = (
            discharge * price * optimizer.eta_discharge
            - charge * price / optimizer.eta_charge
            - optimizer.degradation_per_mwh * (charge + discharge)
        )
        hourly.append(HourlySlot(
            hour=h,
            timestamp=ts,
            net_mw=round(net, 4),
            soc_mwh=round(schedule.soc_mwh[h + 1], 4),
            forecast_price=round(price, 2),
            forecast_revenue=round(slot_revenue, 2),
        ))

    return DispatchResponse(
        hub=req.hub,
        iso=req.iso,
        market=req.market,
        solver_status=schedule.solver_status,
        initial_soc_mwh=round(schedule.soc_mwh[0], 4),
        final_soc_mwh=round(schedule.soc_mwh[-1], 4),
        total_forecast_revenue=round(schedule.forecast_revenue, 2),
        schedule=hourly,
    )
