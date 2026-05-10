/**
 * Adversarial extra tests for pnl.ts — covers gaps in pnl.test.ts.
 */
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

describe("computeIntervalPnl — negative LMP", () => {
  it("discharge at negative LMP produces negative actual revenue", () => {
    // During curtailment events, LMP can go negative
    const result = computeIntervalPnl(makeIv({ discharge_mw: 10 }), -20, cfg);
    // 10 * (-20) * 0.92 - 2 * 10 = -184 - 20 = -204
    expect(result.actualRevenue).toBeLessThan(0);
    expect(result.actualRevenue).toBeCloseTo(10 * -20 * cfg.etaDischarge - cfg.degradationPerMwh * 10);
  });

  it("charge at negative LMP produces positive revenue (being paid to charge)", () => {
    // Charging during negative prices means the grid pays you
    const result = computeIntervalPnl(makeIv({ charge_mw: 10 }), -20, cfg);
    // -(10 * (-20) / 0.92) - 2 * 10 = +217.39... - 20 = +197.39...
    // The formula: discharge_mw * lmp * eta - charge_mw * lmp / eta - degradation
    // With charge_mw=10, discharge_mw=0, lmp=-20:
    // 0 - (10 * (-20) / 0.92) - 2*10 = +217.39 - 20 = +197.39
    const expected = -(10 * -20 / cfg.etaCharge) - cfg.degradationPerMwh * 10;
    expect(result.actualRevenue).toBeCloseTo(expected);
    expect(result.actualRevenue).toBeGreaterThan(0);
  });

  it("zero LMP yields only degradation cost regardless of dispatch direction", () => {
    const chargePnl = computeIntervalPnl(makeIv({ charge_mw: 15 }), 0, cfg);
    const dischargePnl = computeIntervalPnl(makeIv({ discharge_mw: 15 }), 0, cfg);
    // Both should be -degradationPerMwh * mw
    expect(chargePnl.actualRevenue).toBeCloseTo(-cfg.degradationPerMwh * 15);
    expect(dischargePnl.actualRevenue).toBeCloseTo(-cfg.degradationPerMwh * 15);
  });
});

describe("computeIntervalPnl — simultaneous charge and discharge", () => {
  it("both charge and discharge non-zero: formula applies to each independently", () => {
    // charge 10, discharge 5, lmp = 40
    // actual = 5*40*0.92 - 10*40/0.92 - 2*(10+5)
    // actual = 184 - 434.78... - 30 = -280.78...
    const result = computeIntervalPnl(makeIv({ charge_mw: 10, discharge_mw: 5 }), 40, cfg);
    const expected =
      5 * 40 * cfg.etaDischarge -
      10 * 40 / cfg.etaCharge -
      cfg.degradationPerMwh * (10 + 5);
    expect(result.actualRevenue).toBeCloseTo(expected);
  });

  it("symmetric charge and discharge at same LMP is always a loss", () => {
    // Due to round-trip efficiency < 1, charging and immediately discharging loses energy
    const result = computeIntervalPnl(makeIv({ charge_mw: 10, discharge_mw: 10 }), 50, cfg);
    // 10*50*0.92 - 10*50/0.92 - 2*20 = 460 - 543.48 - 40 = -123.48
    expect(result.actualRevenue).toBeLessThan(0);
  });
});

describe("computeDayPnl — negative LMP in price map", () => {
  it("negative actual LMP produces negative actual revenue for discharge", () => {
    const intervals: DispatchInterval[] = [
      makeIv({ discharge_mw: 10, expected_revenue_dollars: 200 }),
    ];
    const priceMap = new Map([["2024-01-08T12:00:00.000Z", -50]]);
    const { actual } = computeDayPnl(intervals, priceMap, cfg);
    // discharge at negative LMP is costly
    expect(actual).toBeLessThan(0);
  });

  it("negative expected revenue is preserved correctly in day sum", () => {
    const intervals: DispatchInterval[] = [
      makeIv({ expected_revenue_dollars: -100, discharge_mw: 10 }),
      makeIv({ timestamp: "2024-01-08T13:00:00.000Z", expected_revenue_dollars: -50, discharge_mw: 5 }),
    ];
    const priceMap = new Map([
      ["2024-01-08T12:00:00.000Z", 30],
      ["2024-01-08T13:00:00.000Z", 30],
    ]);
    const { expected } = computeDayPnl(intervals, priceMap, cfg);
    expect(expected).toBeCloseTo(-150);
  });

  it("breakdown array has one entry per dispatch interval", () => {
    const intervals: DispatchInterval[] = Array.from({ length: 5 }, (_, i) =>
      makeIv({
        timestamp: `2024-01-08T${String(i).padStart(2, "0")}:00:00.000Z`,
        discharge_mw: 5,
        expected_revenue_dollars: 50,
      })
    );
    const priceMap = new Map(
      intervals.map((iv) => [iv.timestamp, 40] as [string, number])
    );
    const { breakdown } = computeDayPnl(intervals, priceMap, cfg);
    expect(breakdown).toHaveLength(5);
  });

  it("actualLmp in breakdown reflects value from price map", () => {
    const intervals: DispatchInterval[] = [makeIv({ discharge_mw: 5 })];
    const priceMap = new Map([["2024-01-08T12:00:00.000Z", 77.5]]);
    const { breakdown } = computeDayPnl(intervals, priceMap, cfg);
    expect(breakdown[0]?.actualLmp).toBe(77.5);
  });

  it("missing timestamp in price map defaults lmp to 0 in breakdown", () => {
    const intervals: DispatchInterval[] = [makeIv({ discharge_mw: 5 })];
    const { breakdown } = computeDayPnl(intervals, new Map(), cfg);
    expect(breakdown[0]?.actualLmp).toBe(0);
  });
});
