import { describe, it, expect } from "vitest";
import { computeIntervalPnl, computeDayPnl } from "../src/pnl.js";
import type { BatteryConfig } from "../src/config.js";
import type { DispatchInterval } from "../src/state.js";

const cfg: BatteryConfig = {
  capacityMwh: 100,
  maxChargeMw: 25,
  maxDischargeMw: 25,
  etaCharge: 0.92,
  etaDischarge: 0.92,
  socMinPct: 0.10,
  socMaxPct: 0.90,
  initialSocPct: 0.50,
  degradationPerMwh: 2.0,
};

function makeIv(overrides: Partial<DispatchInterval> = {}): DispatchInterval {
  return {
    timestamp: "2024-01-08T12:00:00.000Z",
    charge_mw: 0,
    discharge_mw: 0,
    market: "DA_ENERGY",
    expected_revenue_dollars: 0,
    ...overrides,
  };
}

describe("computeIntervalPnl", () => {
  it("zero dispatch yields zero revenue", () => {
    const result = computeIntervalPnl(makeIv(), 50, cfg);
    expect(result.actualRevenue).toBe(0);
  });

  it("discharge at positive price yields positive revenue", () => {
    const result = computeIntervalPnl(makeIv({ discharge_mw: 10 }), 50, cfg);
    // 10 * 50 * 0.92 - 2 * 10 = 460 - 20 = 440
    expect(result.actualRevenue).toBeCloseTo(10 * 50 * 0.92 - 2 * 10);
  });

  it("charge at positive price yields negative revenue (cost)", () => {
    const result = computeIntervalPnl(makeIv({ charge_mw: 10 }), 50, cfg);
    // -(10 * 50 / 0.92) - 2 * 10 = -543.48 - 20
    expect(result.actualRevenue).toBeLessThan(0);
    expect(result.actualRevenue).toBeCloseTo(-(10 * 50 / 0.92) - 2 * 10);
  });

  it("echoes timestamp and MW values", () => {
    const iv = makeIv({ discharge_mw: 5 });
    const result = computeIntervalPnl(iv, 30, cfg);
    expect(result.timestamp).toBe(iv.timestamp);
    expect(result.dischargeMw).toBe(5);
  });

  it("echoes expected revenue from interval", () => {
    const iv = makeIv({ expected_revenue_dollars: 123.45 });
    const result = computeIntervalPnl(iv, 30, cfg);
    expect(result.expectedRevenue).toBeCloseTo(123.45);
  });

  it("degradation cost applies to both charge and discharge", () => {
    const chargePnl = computeIntervalPnl(makeIv({ charge_mw: 10 }), 0, cfg);
    // only degradation: -2 * 10 = -20
    expect(chargePnl.actualRevenue).toBeCloseTo(-20);

    const dischargePnl = computeIntervalPnl(makeIv({ discharge_mw: 10 }), 0, cfg);
    expect(dischargePnl.actualRevenue).toBeCloseTo(-20);
  });
});

describe("computeDayPnl", () => {
  it("sums actual and expected revenue across intervals", () => {
    const intervals: DispatchInterval[] = [
      makeIv({ discharge_mw: 10, expected_revenue_dollars: 100 }),
      makeIv({ timestamp: "2024-01-08T13:00:00.000Z", discharge_mw: 5, expected_revenue_dollars: 50 }),
    ];
    const priceMap = new Map([
      ["2024-01-08T12:00:00.000Z", 50],
      ["2024-01-08T13:00:00.000Z", 40],
    ]);
    const { expected, actual, breakdown } = computeDayPnl(intervals, priceMap, cfg);
    expect(expected).toBeCloseTo(150);
    expect(actual).toBeGreaterThan(0); // discharge at positive prices
    expect(breakdown).toHaveLength(2);
  });

  it("uses 0 price when timestamp missing from map", () => {
    const intervals: DispatchInterval[] = [makeIv({ discharge_mw: 10 })];
    const { actual } = computeDayPnl(intervals, new Map(), cfg);
    // discharge_mw * 0 * eta - degradation * 10 = -20
    expect(actual).toBeCloseTo(-20);
  });

  it("empty intervals returns zeros", () => {
    const { expected, actual, breakdown } = computeDayPnl([], new Map(), cfg);
    expect(expected).toBe(0);
    expect(actual).toBe(0);
    expect(breakdown).toHaveLength(0);
  });
});
