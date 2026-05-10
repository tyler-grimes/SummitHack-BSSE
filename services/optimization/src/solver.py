from typing import Any

import cvxpy as cp
import numpy as np
import numpy.typing as npt

from .battery import BatteryParams


def solve_dispatch(
    params: BatteryParams,
    prices: npt.NDArray[np.float64],
    timestamps: list[str],
    market: str,
) -> tuple[str, list[dict[str, Any]]]:
    T = len(timestamps)
    if T == 0:
        return "optimal", []

    charge = cp.Variable(T, nonneg=True)
    discharge = cp.Variable(T, nonneg=True)
    soc = cp.Variable(T + 1, nonneg=True)

    revenue = cp.sum(
        cp.multiply(discharge, prices) * params.eta_discharge
        - cp.multiply(charge, prices) / params.eta_charge
        - params.degradation_per_mwh * (charge + discharge)
    )

    max_power = max(params.max_charge_mw, params.max_discharge_mw)

    constraints: list[Any] = [
        soc[0] == params.initial_soc_mwh,
        soc[1:] == soc[:T] + cp.multiply(charge, params.eta_charge) - discharge,
        soc >= params.soc_min_mwh,
        soc <= params.soc_max_mwh,
        charge <= params.max_charge_mw,
        discharge <= params.max_discharge_mw,
        charge + discharge <= max_power,
        # Terminal SoC constraint: don't drain the battery for short-term gain.
        # Uses a fixed target (midpoint of SoC window by default) that is
        # independent of the current starting SoC, so the battery recovers
        # even when it starts depleted.
        soc[T] >= params.terminal_soc_mwh,
    ]

    prob = cp.Problem(cp.Maximize(revenue), constraints)
    prob.solve(solver=cp.CLARABEL)

    status: str = prob.status if prob.status is not None else "unknown"

    if status not in ("optimal", "optimal_inaccurate"):
        intervals: list[dict[str, Any]] = [
            {
                "timestamp": ts,
                "charge_mw": 0.0,
                "discharge_mw": 0.0,
                "market": market,
                "expected_revenue_dollars": 0.0,
            }
            for ts in timestamps
        ]
        return status, intervals

    charge_vals: npt.NDArray[np.float64] = (
        charge.value if charge.value is not None else np.zeros(T)
    )
    discharge_vals: npt.NDArray[np.float64] = (
        discharge.value if discharge.value is not None else np.zeros(T)
    )

    intervals = []
    for i, ts in enumerate(timestamps):
        c = float(np.clip(charge_vals[i], 0.0, None))
        d = float(np.clip(discharge_vals[i], 0.0, None))
        rev = (
            d * float(prices[i]) * params.eta_discharge
            - c * float(prices[i]) / params.eta_charge
            - params.degradation_per_mwh * (c + d)
        )
        intervals.append(
            {
                "timestamp": ts,
                "charge_mw": c,
                "discharge_mw": d,
                "market": market,
                "expected_revenue_dollars": rev,
            }
        )

    return status, intervals
