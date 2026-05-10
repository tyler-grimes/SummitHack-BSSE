"""PuLP-based battery dispatch optimizer.

Provides:
- BatteryDispatchOptimizer  — LP solver wrapping PuLP
- rolling_replan             — MPC: replan every hour, execute first step
- Backtester                 — perfect-foresight vs forecast vs naive comparison
- ComparisonReport           — structured result of the three strategies
"""

from __future__ import annotations

import dataclasses
from typing import Sequence

import pulp


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


@dataclasses.dataclass
class DispatchSchedule:
    """Result of a single LP solve over a 24h horizon."""

    # Signed MW per hour: positive = discharging, negative = charging.
    net_mw: list[float]
    # SoC trajectory: T+1 elements (initial + one per hour).
    soc_mwh: list[float]
    # Expected revenue using the forecast prices passed to the solver.
    forecast_revenue: float
    # Actual revenue when realized prices are provided (else None).
    actual_revenue: float | None
    solver_status: str


@dataclasses.dataclass
class ComparisonReport:
    """Daily revenue comparison across three dispatch strategies."""

    date: str
    perfect_foresight_revenue: float
    forecast_driven_revenue: float
    naive_threshold_revenue: float
    # Dollar cost of forecast error vs perfect foresight.
    forecast_gap: float
    # Dollar cost of naive strategy vs forecast-driven.
    naive_gap: float


# ---------------------------------------------------------------------------
# BatteryDispatchOptimizer
# ---------------------------------------------------------------------------


class BatteryDispatchOptimizer:
    """LP-based battery dispatch optimizer using PuLP.

    Battery parameters
    ------------------
    capacity_mwh        : total energy capacity
    max_charge_mw       : maximum charge rate
    max_discharge_mw    : maximum discharge rate
    eta_charge          : one-way charge efficiency  (0 < η ≤ 1)
    eta_discharge       : one-way discharge efficiency (0 < η ≤ 1)
    soc_min_frac        : minimum SoC as fraction of capacity
    soc_max_frac        : maximum SoC as fraction of capacity
    initial_soc_frac    : starting SoC as fraction of capacity
    degradation_per_mwh : $/MWh throughput degradation cost
    """

    def __init__(
        self,
        capacity_mwh: float = 100.0,
        max_charge_mw: float = 25.0,
        max_discharge_mw: float = 25.0,
        eta_charge: float = 0.92,
        eta_discharge: float = 0.92,
        soc_min_frac: float = 0.10,
        soc_max_frac: float = 0.90,
        initial_soc_frac: float = 0.50,
        degradation_per_mwh: float = 1.0,
    ) -> None:
        if not (0 < eta_charge <= 1.0):
            raise ValueError(f"eta_charge must be in (0, 1], got {eta_charge}")
        if not (0 < eta_discharge <= 1.0):
            raise ValueError(f"eta_discharge must be in (0, 1], got {eta_discharge}")
        if soc_min_frac >= soc_max_frac:
            raise ValueError("soc_min_frac must be less than soc_max_frac")
        if not (soc_min_frac <= initial_soc_frac <= soc_max_frac):
            raise ValueError("initial_soc_frac must be within [soc_min_frac, soc_max_frac]")

        self.capacity_mwh = capacity_mwh
        self.max_charge_mw = max_charge_mw
        self.max_discharge_mw = max_discharge_mw
        self.eta_charge = eta_charge
        self.eta_discharge = eta_discharge
        self.soc_min_mwh = soc_min_frac * capacity_mwh
        self.soc_max_mwh = soc_max_frac * capacity_mwh
        self.initial_soc_mwh = initial_soc_frac * capacity_mwh
        self.degradation_per_mwh = degradation_per_mwh

    def uncertainty_adjusted_prices(
        self,
        p10: Sequence[float],
        p50: Sequence[float],
        p90: Sequence[float],
        confidence: float = 1.0,
    ) -> list[float]:
        """Build a conservative price vector that accounts for forecast uncertainty.

        For each hour:
          - High confidence (confidence → 1.0): use p50 as-is.
          - Low confidence (confidence → 0.0): shade discharge hours down toward p10,
            charge hours up toward p90. This makes the LP more conservative when the
            model is uncertain — it won't commit to discharging if the price might be
            lower than p50, and won't commit to charging if the price might be higher.

        spread_weight = 1 - confidence  (0 = trust p50, 1 = fully conservative)

        adjusted[t] =
          p50[t] - spread_weight * 0.5 * (p90[t] - p10[t])   if p50[t] > mean (discharge likely)
          p50[t] + spread_weight * 0.5 * (p90[t] - p10[t])   if p50[t] < mean (charge likely)

        The factor of 0.5 prevents the adjustment from overcorrecting to the extreme quantile.
        """
        if len(p10) != len(p50) or len(p50) != len(p90):
            raise ValueError("p10, p50, p90 must have the same length")

        spread_weight = max(0.0, min(1.0, 1.0 - confidence))
        if spread_weight == 0.0:
            return list(p50)

        mean_price = sum(p50) / len(p50) if p50 else 0.0
        adjusted: list[float] = []
        for lo, mid, hi in zip(p10, p50, p90):
            spread = (hi - lo) * 0.5 * spread_weight
            if mid >= mean_price:
                # Discharge-favoured hour — shade down to be conservative
                adjusted.append(mid - spread)
            else:
                # Charge-favoured hour — shade up to be conservative
                adjusted.append(mid + spread)
        return adjusted

    def solve(
        self,
        forecast_prices: Sequence[float],
        actual_prices: Sequence[float] | None = None,
        initial_soc_mwh: float | None = None,
    ) -> DispatchSchedule:
        """Solve one LP horizon.

        Parameters
        ----------
        forecast_prices : 24-element price array used as the LP objective.
        actual_prices   : if provided, compute realized revenue against these.
        initial_soc_mwh : override starting SoC (used by MPC rollout).

        Returns
        -------
        DispatchSchedule with net_mw, soc_mwh, forecast_revenue, actual_revenue.

        LP formulation
        --------------
        Variables per hour t:
            c[t] >= 0   charge MW
            d[t] >= 0   discharge MW

        Objective (maximize):
            Σ_t  d[t] * price[t] * η_d
                - c[t] * price[t] / η_c
                - degradation * (c[t] + d[t])

        Constraints:
            SoC continuity : soc[t+1] = soc[t] + c[t]*η_c - d[t]
            SoC bounds     : soc_min ≤ soc[t] ≤ soc_max  ∀t
            Power limits   : c[t] ≤ max_charge, d[t] ≤ max_discharge
            No simultaneous: c[t] + d[t] ≤ max(max_charge, max_discharge)
              — a single signed variable would also work but separate
                variables let PuLP keep the LP continuous (no binary needed).
        """
        T = len(forecast_prices)
        if T == 0:
            return DispatchSchedule(
                net_mw=[],
                soc_mwh=[initial_soc_mwh if initial_soc_mwh is not None else self.initial_soc_mwh],
                forecast_revenue=0.0,
                actual_revenue=0.0 if actual_prices is not None else None,
                solver_status="optimal",
            )

        soc0 = initial_soc_mwh if initial_soc_mwh is not None else self.initial_soc_mwh
        max_power = max(self.max_charge_mw, self.max_discharge_mw)

        prob = pulp.LpProblem("battery_dispatch", pulp.LpMaximize)

        c = [pulp.LpVariable(f"c_{t}", lowBound=0.0, upBound=self.max_charge_mw) for t in range(T)]
        d = [pulp.LpVariable(f"d_{t}", lowBound=0.0, upBound=self.max_discharge_mw) for t in range(T)]
        soc = [pulp.LpVariable(f"soc_{t}", lowBound=self.soc_min_mwh, upBound=self.soc_max_mwh) for t in range(T + 1)]

        # Objective
        prob += pulp.lpSum(
            d[t] * forecast_prices[t] * self.eta_discharge
            - c[t] * forecast_prices[t] / self.eta_charge
            - self.degradation_per_mwh * (c[t] + d[t])
            for t in range(T)
        )

        # Initial SoC
        prob += soc[0] == soc0

        for t in range(T):
            # SoC continuity
            prob += soc[t + 1] == soc[t] + c[t] * self.eta_charge - d[t]
            # No simultaneous charge + discharge
            prob += c[t] + d[t] <= max_power

        status_str = pulp.LpStatus[prob.solve(pulp.PULP_CBC_CMD(msg=0))]

        # Extract solution — fall back to zeros if infeasible
        if prob.status != pulp.LpStatusNotSolved and pulp.value(prob.objective) is not None:
            c_vals = [max(0.0, pulp.value(c[t]) or 0.0) for t in range(T)]
            d_vals = [max(0.0, pulp.value(d[t]) or 0.0) for t in range(T)]
            soc_vals = [pulp.value(soc[t]) or 0.0 for t in range(T + 1)]
        else:
            c_vals = [0.0] * T
            d_vals = [0.0] * T
            soc_vals = [soc0] + [soc0] * T

        net_mw = [d_vals[t] - c_vals[t] for t in range(T)]

        forecast_revenue = sum(
            d_vals[t] * forecast_prices[t] * self.eta_discharge
            - c_vals[t] * forecast_prices[t] / self.eta_charge
            - self.degradation_per_mwh * (c_vals[t] + d_vals[t])
            for t in range(T)
        )

        actual_revenue: float | None = None
        if actual_prices is not None:
            actual_revenue = sum(
                d_vals[t] * actual_prices[t] * self.eta_discharge
                - c_vals[t] * actual_prices[t] / self.eta_charge
                - self.degradation_per_mwh * (c_vals[t] + d_vals[t])
                for t in range(T)
            )

        return DispatchSchedule(
            net_mw=net_mw,
            soc_mwh=soc_vals,
            forecast_revenue=forecast_revenue,
            actual_revenue=actual_revenue,
            solver_status=status_str,
        )

    def with_soc(self, new_soc_frac: float) -> "BatteryDispatchOptimizer":
        """Return a copy of this optimizer with a different starting SoC."""
        return BatteryDispatchOptimizer(
            capacity_mwh=self.capacity_mwh,
            max_charge_mw=self.max_charge_mw,
            max_discharge_mw=self.max_discharge_mw,
            eta_charge=self.eta_charge,
            eta_discharge=self.eta_discharge,
            soc_min_frac=self.soc_min_mwh / self.capacity_mwh,
            soc_max_frac=self.soc_max_mwh / self.capacity_mwh,
            initial_soc_frac=new_soc_frac,
            degradation_per_mwh=self.degradation_per_mwh,
        )


# ---------------------------------------------------------------------------
# Rolling replan (MPC)
# ---------------------------------------------------------------------------


def rolling_replan(
    optimizer: BatteryDispatchOptimizer,
    forecast_windows: Sequence[Sequence[float]],
    actual_prices: Sequence[float] | None = None,
) -> tuple[list[float], list[float], float]:
    """Model predictive control: replan every hour on a fresh 24h window.

    For each hour h:
      1. Solve LP over forecast_windows[h] (24h lookahead).
      2. Execute only the first hour's command (net_mw[0]).
      3. Advance SoC using actual physics.
      4. Replan at h+1 with the updated SoC.

    Parameters
    ----------
    optimizer        : configured BatteryDispatchOptimizer (initial SoC is used at h=0).
    forecast_windows : list of N 24h forecast price arrays, one per execution step.
    actual_prices    : realized prices for each executed step (len == N).
                       Used only to compute actual revenue — not fed into LP.

    Returns
    -------
    executed_net_mw  : list of N executed MW values (signed).
    soc_trajectory   : list of N+1 SoC values in MWh.
    actual_revenue   : total realized revenue over all N steps.
    """
    N = len(forecast_windows)
    executed_net_mw: list[float] = []
    soc_trajectory: list[float] = [optimizer.initial_soc_mwh]
    total_actual_revenue = 0.0

    current_soc = optimizer.initial_soc_mwh

    for h in range(N):
        schedule = optimizer.solve(
            forecast_prices=forecast_windows[h],
            initial_soc_mwh=current_soc,
        )

        # Execute first hour only
        net = schedule.net_mw[0] if schedule.net_mw else 0.0
        executed_net_mw.append(net)

        # Advance SoC using actual physics
        if net >= 0:
            # Discharging: remove energy from battery
            current_soc = current_soc - net
        else:
            # Charging: add energy (charge_mw = -net, apply eta_charge)
            current_soc = current_soc + (-net) * optimizer.eta_charge

        # Clamp to physical bounds
        current_soc = max(optimizer.soc_min_mwh, min(optimizer.soc_max_mwh, current_soc))
        soc_trajectory.append(current_soc)

        # Accumulate actual revenue if realized prices are provided
        if actual_prices is not None:
            p = actual_prices[h]
            charge_mw = max(0.0, -net)
            discharge_mw = max(0.0, net)
            total_actual_revenue += (
                discharge_mw * p * optimizer.eta_discharge
                - charge_mw * p / optimizer.eta_charge
                - optimizer.degradation_per_mwh * (charge_mw + discharge_mw)
            )

    return executed_net_mw, soc_trajectory, total_actual_revenue


# ---------------------------------------------------------------------------
# Naive threshold strategy
# ---------------------------------------------------------------------------


def _naive_dispatch(
    optimizer: BatteryDispatchOptimizer,
    prices: Sequence[float],
    initial_soc_mwh: float | None = None,
) -> tuple[list[float], float]:
    """Threshold strategy: charge below mean price, discharge above.

    Serves as a simple benchmark — no LP, no lookahead.
    Returns (net_mw per hour, actual revenue).
    """
    mean_price = sum(prices) / len(prices) if prices else 0.0
    soc = initial_soc_mwh if initial_soc_mwh is not None else optimizer.initial_soc_mwh
    net_mw: list[float] = []
    revenue = 0.0

    for p in prices:
        if p < mean_price:
            # Charge at full rate if room available
            charge = min(
                optimizer.max_charge_mw,
                (optimizer.soc_max_mwh - soc) / optimizer.eta_charge,
            )
            charge = max(0.0, charge)
            soc += charge * optimizer.eta_charge
            net = -charge
            revenue += (
                -charge * p / optimizer.eta_charge
                - optimizer.degradation_per_mwh * charge
            )
        else:
            # Discharge at full rate if energy available
            discharge = min(
                optimizer.max_discharge_mw,
                soc - optimizer.soc_min_mwh,
            )
            discharge = max(0.0, discharge)
            soc -= discharge
            net = discharge
            revenue += (
                discharge * p * optimizer.eta_discharge
                - optimizer.degradation_per_mwh * discharge
            )

        net_mw.append(net)

    return net_mw, revenue


# ---------------------------------------------------------------------------
# Backtester
# ---------------------------------------------------------------------------


class Backtester:
    """Runs three dispatch strategies over historical daily price data.

    Strategies compared
    -------------------
    1. Perfect foresight  — LP solved with actual realized prices (upper bound).
    2. Forecast-driven    — LP solved with forecast prices, evaluated on actuals.
    3. Naive threshold    — charge below mean, discharge above (no LP).
    """

    def __init__(self, optimizer: BatteryDispatchOptimizer) -> None:
        self.optimizer = optimizer

    def run_day(
        self,
        date: str,
        forecast_prices: Sequence[float],
        actual_prices: Sequence[float],
    ) -> ComparisonReport:
        """Compare all three strategies for a single 24h period.

        Parameters
        ----------
        date            : ISO date string for the report label.
        forecast_prices : 24h forecast used by forecast-driven strategy.
        actual_prices   : 24h realized prices used by all strategies for revenue.
        """
        if len(forecast_prices) != 24 or len(actual_prices) != 24:
            raise ValueError("Both forecast_prices and actual_prices must have exactly 24 elements")

        # 1. Perfect foresight: solve LP with actual prices
        pf_schedule = self.optimizer.solve(
            forecast_prices=actual_prices,
            actual_prices=actual_prices,
        )
        pf_revenue = pf_schedule.actual_revenue or 0.0

        # 2. Forecast-driven: solve LP with forecast, evaluate on actuals
        fc_schedule = self.optimizer.solve(
            forecast_prices=forecast_prices,
            actual_prices=actual_prices,
        )
        fc_revenue = fc_schedule.actual_revenue or 0.0

        # 3. Naive threshold
        _, naive_revenue = _naive_dispatch(self.optimizer, actual_prices)

        return ComparisonReport(
            date=date,
            perfect_foresight_revenue=round(pf_revenue, 2),
            forecast_driven_revenue=round(fc_revenue, 2),
            naive_threshold_revenue=round(naive_revenue, 2),
            forecast_gap=round(pf_revenue - fc_revenue, 2),
            naive_gap=round(fc_revenue - naive_revenue, 2),
        )

    def run_period(
        self,
        dates: Sequence[str],
        forecast_prices_by_day: Sequence[Sequence[float]],
        actual_prices_by_day: Sequence[Sequence[float]],
        carry_soc: bool = True,
    ) -> list[ComparisonReport]:
        """Run backtester over multiple days.

        Parameters
        ----------
        carry_soc : if True, the ending SoC of each day is carried into the next.
                    If False, reset to initial_soc_mwh each day.
        """
        if not (len(dates) == len(forecast_prices_by_day) == len(actual_prices_by_day)):
            raise ValueError("dates, forecast_prices_by_day, and actual_prices_by_day must have the same length")

        reports: list[ComparisonReport] = []
        soc = self.optimizer.initial_soc_mwh

        for date, fc_prices, act_prices in zip(dates, forecast_prices_by_day, actual_prices_by_day):
            # Solve each strategy from current SoC
            day_optimizer = BatteryDispatchOptimizer(
                capacity_mwh=self.optimizer.capacity_mwh,
                max_charge_mw=self.optimizer.max_charge_mw,
                max_discharge_mw=self.optimizer.max_discharge_mw,
                eta_charge=self.optimizer.eta_charge,
                eta_discharge=self.optimizer.eta_discharge,
                soc_min_frac=self.optimizer.soc_min_mwh / self.optimizer.capacity_mwh,
                soc_max_frac=self.optimizer.soc_max_mwh / self.optimizer.capacity_mwh,
                initial_soc_frac=soc / self.optimizer.capacity_mwh,
                degradation_per_mwh=self.optimizer.degradation_per_mwh,
            )

            report = day_optimizer.run_day(date, fc_prices, act_prices) if False else \
                Backtester(day_optimizer).run_day(date, fc_prices, act_prices)
            reports.append(report)

            if carry_soc:
                # Advance SoC using forecast-driven schedule (what the agent would actually execute)
                fc_schedule = day_optimizer.solve(
                    forecast_prices=fc_prices,
                    actual_prices=act_prices,
                )
                soc = fc_schedule.soc_mwh[-1]

        return reports

    @staticmethod
    def summary(reports: list[ComparisonReport]) -> dict[str, float]:
        """Aggregate totals and averages across all daily reports."""
        n = len(reports)
        if n == 0:
            return {}
        return {
            "days": float(n),
            "total_perfect_foresight": round(sum(r.perfect_foresight_revenue for r in reports), 2),
            "total_forecast_driven": round(sum(r.forecast_driven_revenue for r in reports), 2),
            "total_naive": round(sum(r.naive_threshold_revenue for r in reports), 2),
            "total_forecast_gap": round(sum(r.forecast_gap for r in reports), 2),
            "total_naive_gap": round(sum(r.naive_gap for r in reports), 2),
            "avg_daily_forecast_gap": round(sum(r.forecast_gap for r in reports) / n, 2),
            "avg_daily_naive_gap": round(sum(r.naive_gap for r in reports) / n, 2),
            "forecast_efficiency_pct": round(
                sum(r.forecast_driven_revenue for r in reports)
                / max(sum(r.perfect_foresight_revenue for r in reports), 1e-9)
                * 100,
                1,
            ),
        }
