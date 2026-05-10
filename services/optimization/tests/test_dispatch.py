"""Tests for src/dispatch.py — BatteryDispatchOptimizer, rolling_replan, Backtester."""

import math
import pytest

from src.dispatch import (
    Backtester,
    BatteryDispatchOptimizer,
    ComparisonReport,
    rolling_replan,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _opt(**kwargs) -> BatteryDispatchOptimizer:
    defaults = dict(
        capacity_mwh=100.0,
        max_charge_mw=25.0,
        max_discharge_mw=25.0,
        eta_charge=0.92,
        eta_discharge=0.92,
        soc_min_frac=0.10,
        soc_max_frac=0.90,
        initial_soc_frac=0.50,
        degradation_per_mwh=1.0,
    )
    defaults.update(kwargs)
    return BatteryDispatchOptimizer(**defaults)


def _flat(n: int, price: float) -> list[float]:
    return [price] * n


def _peak_valley(n: int = 24, low: float = 20.0, high: float = 80.0) -> list[float]:
    half = n // 2
    return [low] * half + [high] * (n - half)


# ---------------------------------------------------------------------------
# BatteryDispatchOptimizer — construction validation
# ---------------------------------------------------------------------------


def test_invalid_eta_charge_raises() -> None:
    with pytest.raises(ValueError, match="eta_charge"):
        BatteryDispatchOptimizer(eta_charge=0.0)


def test_invalid_eta_discharge_raises() -> None:
    with pytest.raises(ValueError, match="eta_discharge"):
        BatteryDispatchOptimizer(eta_discharge=1.1)


def test_soc_min_ge_max_raises() -> None:
    with pytest.raises(ValueError, match="soc_min_frac"):
        BatteryDispatchOptimizer(soc_min_frac=0.9, soc_max_frac=0.5)


def test_initial_soc_out_of_bounds_raises() -> None:
    with pytest.raises(ValueError, match="initial_soc_frac"):
        BatteryDispatchOptimizer(soc_min_frac=0.1, soc_max_frac=0.9, initial_soc_frac=0.95)


# ---------------------------------------------------------------------------
# BatteryDispatchOptimizer.solve — return shape
# ---------------------------------------------------------------------------


def test_solve_empty_prices_returns_empty_schedule() -> None:
    opt = _opt()
    s = opt.solve([])
    assert s.net_mw == []
    assert s.solver_status == "optimal"


def test_solve_returns_24_net_mw_values() -> None:
    opt = _opt()
    s = opt.solve(_flat(24, 30.0))
    assert len(s.net_mw) == 24


def test_solve_soc_trajectory_length_is_t_plus_1() -> None:
    opt = _opt()
    s = opt.solve(_flat(24, 30.0))
    assert len(s.soc_mwh) == 25


def test_solve_soc_starts_at_initial() -> None:
    opt = _opt(initial_soc_frac=0.6)
    s = opt.solve(_flat(24, 30.0))
    assert s.soc_mwh[0] == pytest.approx(60.0, abs=1e-4)


# ---------------------------------------------------------------------------
# BatteryDispatchOptimizer.solve — SoC bounds respected
# ---------------------------------------------------------------------------


def test_soc_never_below_min() -> None:
    opt = _opt(degradation_per_mwh=0.01)
    s = opt.solve(_peak_valley())
    for soc in s.soc_mwh:
        assert soc >= opt.soc_min_mwh - 1e-4, f"SoC {soc} < min {opt.soc_min_mwh}"


def test_soc_never_above_max() -> None:
    opt = _opt(degradation_per_mwh=0.01)
    s = opt.solve(_peak_valley())
    for soc in s.soc_mwh:
        assert soc <= opt.soc_max_mwh + 1e-4, f"SoC {soc} > max {opt.soc_max_mwh}"


# ---------------------------------------------------------------------------
# BatteryDispatchOptimizer.solve — economic logic
# ---------------------------------------------------------------------------


def test_discharge_at_high_prices() -> None:
    """Battery should discharge in the high-price second half."""
    opt = _opt(degradation_per_mwh=0.1)
    s = opt.solve(_peak_valley())
    peak_discharge = sum(max(0.0, net) for net in s.net_mw[12:])
    assert peak_discharge > 0.1, f"Expected discharge at peak, got {peak_discharge}"


def test_charge_at_low_prices() -> None:
    """Battery should charge in the low-price first half."""
    opt = _opt(degradation_per_mwh=0.1)
    s = opt.solve(_peak_valley())
    offpeak_charge = sum(max(0.0, -net) for net in s.net_mw[:12])
    assert offpeak_charge > 0.1, f"Expected charging at off-peak, got {offpeak_charge}"


def test_flat_prices_no_charge_then_discharge_cycle() -> None:
    """Flat prices with high degradation: charging then discharging has negative net value.
    Start at soc_min so there is no pre-stored energy to discharge — any positive
    revenue would require a charge-then-discharge cycle, which degradation makes unprofitable."""
    opt = _opt(degradation_per_mwh=5.0, initial_soc_frac=0.10)
    s = opt.solve(_flat(24, 40.0))
    total_charge = sum(max(0.0, -net) for net in s.net_mw)
    # With degradation=$5/MWh and flat prices, cycling yields no spread — charging should be ~0.
    assert total_charge < 1.0, f"Unexpected charging at flat prices with high degradation: {total_charge}"


def test_actual_revenue_computed_when_provided() -> None:
    opt = _opt(degradation_per_mwh=0.1)
    prices = _peak_valley()
    actual = _flat(24, 50.0)
    s = opt.solve(forecast_prices=prices, actual_prices=actual)
    assert s.actual_revenue is not None
    assert isinstance(s.actual_revenue, float)


def test_actual_revenue_none_when_not_provided() -> None:
    opt = _opt()
    s = opt.solve(_flat(24, 30.0))
    assert s.actual_revenue is None


def test_power_limits_respected() -> None:
    """charge and discharge MW must not exceed configured limits."""
    opt = _opt(max_charge_mw=10.0, max_discharge_mw=15.0, degradation_per_mwh=0.1)
    s = opt.solve(_peak_valley())
    for net in s.net_mw:
        charge = max(0.0, -net)
        discharge = max(0.0, net)
        assert charge <= 10.0 + 1e-4, f"Charge {charge} exceeds max_charge_mw"
        assert discharge <= 15.0 + 1e-4, f"Discharge {discharge} exceeds max_discharge_mw"


def test_perfect_foresight_revenue_nonnegative_for_spread_prices() -> None:
    """With clear arbitrage, revenue should be positive."""
    opt = _opt(degradation_per_mwh=0.1)
    s = opt.solve(_peak_valley())
    assert s.forecast_revenue > 0.0


# ---------------------------------------------------------------------------
# rolling_replan
# ---------------------------------------------------------------------------


def test_rolling_replan_returns_correct_lengths() -> None:
    opt = _opt()
    windows = [_flat(24, 30.0 + i) for i in range(10)]
    net_mw, soc_traj, _ = rolling_replan(opt, windows)
    assert len(net_mw) == 10
    assert len(soc_traj) == 11


def test_rolling_replan_soc_stays_within_bounds() -> None:
    opt = _opt(degradation_per_mwh=0.1)
    windows = [_peak_valley() for _ in range(24)]
    _, soc_traj, _ = rolling_replan(opt, windows)
    for soc in soc_traj:
        assert soc >= opt.soc_min_mwh - 1e-4
        assert soc <= opt.soc_max_mwh + 1e-4


def test_rolling_replan_actual_revenue_computed() -> None:
    opt = _opt(degradation_per_mwh=0.1)
    windows = [_peak_valley() for _ in range(24)]
    actual = [_peak_valley()[h % 24] for h in range(24)]
    _, _, revenue = rolling_replan(opt, windows, actual_prices=actual)
    assert isinstance(revenue, float)


def test_rolling_replan_empty_windows() -> None:
    opt = _opt()
    net_mw, soc_traj, revenue = rolling_replan(opt, [])
    assert net_mw == []
    assert len(soc_traj) == 1
    assert revenue == 0.0


# ---------------------------------------------------------------------------
# Backtester.run_day
# ---------------------------------------------------------------------------


def test_run_day_returns_comparison_report() -> None:
    bt = Backtester(_opt(degradation_per_mwh=0.1))
    report = bt.run_day("2024-01-01", _peak_valley(), _peak_valley())
    assert isinstance(report, ComparisonReport)
    assert report.date == "2024-01-01"


def test_run_day_perfect_foresight_ge_forecast_driven() -> None:
    """Perfect foresight should always earn >= forecast-driven revenue."""
    bt = Backtester(_opt(degradation_per_mwh=0.1))
    fc = _peak_valley(low=18.0, high=75.0)
    actual = _peak_valley(low=20.0, high=80.0)
    report = bt.run_day("2024-01-01", fc, actual)
    assert report.perfect_foresight_revenue >= report.forecast_driven_revenue - 1e-4


def test_run_day_forecast_gap_is_difference() -> None:
    bt = Backtester(_opt(degradation_per_mwh=0.1))
    report = bt.run_day("2024-01-01", _peak_valley(), _peak_valley())
    expected_gap = report.perfect_foresight_revenue - report.forecast_driven_revenue
    assert report.forecast_gap == pytest.approx(expected_gap, abs=0.01)


def test_run_day_wrong_length_raises() -> None:
    bt = Backtester(_opt())
    with pytest.raises(ValueError, match="24 elements"):
        bt.run_day("2024-01-01", _flat(12, 30.0), _flat(24, 30.0))


def test_run_day_identical_forecast_and_actual_zero_gap() -> None:
    """When forecast == actual, perfect foresight gap should be ~0."""
    bt = Backtester(_opt(degradation_per_mwh=0.1))
    prices = _peak_valley()
    report = bt.run_day("2024-01-01", prices, prices)
    assert abs(report.forecast_gap) < 1e-2


# ---------------------------------------------------------------------------
# Backtester.run_period
# ---------------------------------------------------------------------------


def test_run_period_returns_one_report_per_day() -> None:
    bt = Backtester(_opt(degradation_per_mwh=0.1))
    dates = ["2024-01-01", "2024-01-02", "2024-01-03"]
    fc = [_peak_valley()] * 3
    act = [_peak_valley()] * 3
    reports = bt.run_period(dates, fc, act)
    assert len(reports) == 3


def test_run_period_mismatched_lengths_raises() -> None:
    bt = Backtester(_opt())
    with pytest.raises(ValueError):
        bt.run_period(["2024-01-01"], [_flat(24, 30.0)], [])


# ---------------------------------------------------------------------------
# Backtester.summary
# ---------------------------------------------------------------------------


def test_summary_empty_returns_empty_dict() -> None:
    assert Backtester.summary([]) == {}


def test_summary_totals_correct() -> None:
    bt = Backtester(_opt(degradation_per_mwh=0.1))
    dates = ["2024-01-01", "2024-01-02"]
    fc = [_peak_valley()] * 2
    act = [_peak_valley()] * 2
    reports = bt.run_period(dates, fc, act)
    summary = Backtester.summary(reports)

    assert summary["days"] == 2.0
    assert summary["total_perfect_foresight"] == pytest.approx(
        sum(r.perfect_foresight_revenue for r in reports), abs=0.01
    )
    assert summary["total_forecast_gap"] == pytest.approx(
        sum(r.forecast_gap for r in reports), abs=0.01
    )
    assert 0.0 <= summary["forecast_efficiency_pct"] <= 100.0


# ---------------------------------------------------------------------------
# /dispatch endpoint
# ---------------------------------------------------------------------------


def test_dispatch_endpoint_missing_forecast_service(monkeypatch) -> None:
    """When forecasting service is unreachable, /dispatch should return 502."""
    import httpx
    from fastapi.testclient import TestClient
    from src.main import app

    def _raise(*a, **kw):
        raise httpx.ConnectError("refused")

    monkeypatch.setattr(httpx.AsyncClient, "post", _raise)
    client = TestClient(app, raise_server_exceptions=False)
    resp = client.post("/dispatch", json={"hub": "HB_NORTH"})
    assert resp.status_code == 502
