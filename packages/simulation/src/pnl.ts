import type { BatteryConfig } from "./config.js";
import type { DispatchInterval } from "./state.js";

export interface IntervalPnl {
  timestamp: string;
  chargeMw: number;
  dischargeMw: number;
  actualLmp: number;
  expectedRevenue: number;
  actualRevenue: number;
}

export function computeIntervalPnl(
  iv: DispatchInterval,
  actualLmp: number,
  cfg: BatteryConfig
): IntervalPnl {
  const expectedRevenue = iv.expected_revenue_dollars;
  const actualRevenue =
    iv.discharge_mw * actualLmp * cfg.etaDischarge -
    iv.charge_mw * actualLmp / cfg.etaCharge -
    cfg.degradationPerMwh * (iv.charge_mw + iv.discharge_mw);

  return {
    timestamp: iv.timestamp,
    chargeMw: iv.charge_mw,
    dischargeMw: iv.discharge_mw,
    actualLmp,
    expectedRevenue,
    actualRevenue,
  };
}

export function computeDayPnl(
  intervals: DispatchInterval[],
  actualPrices: Map<string, number>,
  cfg: BatteryConfig
): { expected: number; actual: number; breakdown: IntervalPnl[] } {
  const breakdown: IntervalPnl[] = [];
  let expected = 0;
  let actual = 0;

  for (const iv of intervals) {
    const lmp = actualPrices.get(iv.timestamp) ?? 0;
    const detail = computeIntervalPnl(iv, lmp, cfg);
    breakdown.push(detail);
    expected += detail.expectedRevenue;
    actual += detail.actualRevenue;
  }

  return { expected, actual, breakdown };
}
