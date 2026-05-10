import { describe, it, expect, vi, beforeEach } from "vitest";
import { runSimulation } from "../src/runner.js";
import type { SimConfig } from "../src/config.js";
import { DEFAULT_BATTERY } from "../src/config.js";

const BASE_CONFIG: SimConfig = {
  assetId: "TEST-BESS",
  iso: "ERCOT",
  node: "HB_NORTH",
  markets: ["DA_ENERGY"],
  startDate: "2024-01-08",
  endDate: "2024-01-10",
  basePriceMwh: 35,
  battery: DEFAULT_BATTERY,
  forecastingUrl: "http://forecasting.test",
  optimizationUrl: "http://optimization.test",
};

function makeForecastResponse(node: string) {
  return [
    {
      iso: "ERCOT",
      node,
      market: "DA_ENERGY",
      intervals: Array.from({ length: 24 }, (_, h) => ({
        timestamp: `2024-01-08T${String(h).padStart(2, "0")}:00:00.000Z`,
        mean: 35.0,
        p10: 30.0,
        p90: 40.0,
      })),
      model_id: "test-model",
      confidence: 0.8,
    },
  ];
}

function makeOptimizeResponse(assetId: string) {
  return {
    asset_id: assetId,
    intervals: Array.from({ length: 24 }, (_, h) => ({
      timestamp: `2024-01-08T${String(h).padStart(2, "0")}:00:00.000Z`,
      charge_mw: h < 12 ? 10 : 0,
      discharge_mw: h >= 12 ? 10 : 0,
      market: "DA_ENERGY",
      expected_revenue_dollars: h >= 12 ? 150 : -80,
    })),
    total_expected_revenue_dollars: 840,
    solver_status: "optimal",
  };
}

beforeEach(() => {
  vi.stubGlobal(
    "fetch",
    vi.fn((url: string) => {
      if ((url).includes("/forecast")) {
        return Promise.resolve({
          ok: true,
          json: () => Promise.resolve(makeForecastResponse("HB_NORTH")),
        });
      }
      if ((url).includes("/optimize")) {
        return Promise.resolve({
          ok: true,
          json: () => Promise.resolve(makeOptimizeResponse("TEST-BESS")),
        });
      }
      return Promise.resolve({ ok: false, text: () => Promise.resolve("not found") });
    })
  );
});

describe("runSimulation", () => {
  it("returns one DayResult per day in range", async () => {
    const result = await runSimulation(BASE_CONFIG);
    expect(result.days).toHaveLength(3); // Jan 8, 9, 10
  });

  it("daysSimulated matches days array length", async () => {
    const result = await runSimulation(BASE_CONFIG);
    expect(result.daysSimulated).toBe(result.days.length);
  });

  it("totalExpectedRevenue sums daily expected", async () => {
    const result = await runSimulation(BASE_CONFIG);
    const sum = result.days.reduce((s, d) => s + d.expectedRevenueDollars, 0);
    expect(result.totalExpectedRevenueDollars).toBeCloseTo(sum);
  });

  it("totalActualRevenue sums daily actual", async () => {
    const result = await runSimulation(BASE_CONFIG);
    const sum = result.days.reduce((s, d) => s + d.actualRevenueDollars, 0);
    expect(result.totalActualRevenueDollars).toBeCloseTo(sum);
  });

  it("day results have date strings in YYYY-MM-DD format", async () => {
    const result = await runSimulation(BASE_CONFIG);
    for (const d of result.days) {
      expect(d.date).toMatch(/^\d{4}-\d{2}-\d{2}$/);
    }
  });

  it("SoC start of first day equals initialSocPct", async () => {
    const result = await runSimulation(BASE_CONFIG);
    expect(result.days[0]?.socStartPct).toBeCloseTo(0.50);
  });

  it("handles service error gracefully — day has error status, not thrown", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(() =>
        Promise.resolve({ ok: false, text: () => Promise.resolve("Service Unavailable") })
      )
    );
    const result = await runSimulation(BASE_CONFIG);
    expect(result.days).toHaveLength(3);
    expect(result.days[0]?.solverStatus).toContain("error");
  });

  it("single-day range returns exactly one result", async () => {
    const config = { ...BASE_CONFIG, startDate: "2024-01-08", endDate: "2024-01-08" };
    const result = await runSimulation(config);
    expect(result.days).toHaveLength(1);
  });

  it("config is echoed in result", async () => {
    const result = await runSimulation(BASE_CONFIG);
    expect(result.config.assetId).toBe("TEST-BESS");
    expect(result.config.iso).toBe("ERCOT");
  });

  it("totalCycles is positive when dispatch occurs", async () => {
    const result = await runSimulation(BASE_CONFIG);
    expect(result.totalCycles).toBeGreaterThan(0);
  });
});
