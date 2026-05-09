from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

app = FastAPI(title="Optimization Service", version="0.1.0")


class OptimizeRequest(BaseModel):
    asset_id: str
    forecasts: dict  # market -> list of { timestamp, mean, p10, p90 }
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
    solver_status: str  # "optimal" | "infeasible" | "timeout"


@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/optimize", response_model=OptimizeResponse)
async def optimize(req: OptimizeRequest) -> OptimizeResponse:
    # TODO: fetch battery state from Redis, run CVXPY solver
    raise HTTPException(status_code=501, detail="Not implemented")
