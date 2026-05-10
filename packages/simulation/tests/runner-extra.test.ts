/**
 * Adversarial extra tests for runner.ts — covers gaps in runner.test.ts.
 */
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
  endDate: "2024-01-08", // single day for most tests
  basePriceMwh: 35,
  battery: DEFAULT_BATTERY,
  forecastingUrl: "http://forecasting.test",
  optimizationUrl: "http://optimization.test",
};

function makeOptimizeResponse(assetId = "TEST-BESS") {
  return {
    asset_id: assetId,
    intervals: Array.from({ length: 24 }, (_, h) => ({
      timestamp: `2024-01-08T${String(h).padStart(2, "0")}:00:00.000Z`,
      charge_mw: h < 8 ? 10 : 0,
      discharge_mw: h >= 16 ? 10 : 0,
      market: "DA_ENERGY",
      expected_revenue_dollars: h >= 16 ? 150 : h < 8 ? -80 : 0,
    })),
    total_expected_revenue_dollars: 640,
    solver_status: "optimal",
  };
}

function makeForecastResponse(node: string, market = "DA_ENERGY") {
  return [
    {
      iso: "ERCOT",
      node,
      market,
      intervals: Array.from({ length: 24 }, (_, h) => ({
        timestamp: `2024-01-08T${String(h).padStart(2, "0")}:00:00.000Z`,
        mean: 35.0,
        p10: 29.75,
        p90: 40.25,
      })),
      model_id: "test-model",
      confidence: 0.85,
    },
  ];
}

// ---------------------------------------------------------------------------
// Empty date range
// ---------------------------------------------------------------------------

describe("runSimulation — empty date range", () => {
  beforeEach(() => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({
      ok: true,
      json: () => Promise.resolve([]),
    }));
  });

  it("startDate > endDate returns 0 days", async () => {
    const config = { ...BASE_CONFIG, startDate: "2024-01-10", endDate: "2024-01-08" };
    const result = await runSimulation(config);
    expect(result.days).toHaveLength(0);
    expect(result.daysSimulated).toBe(0);
  });

  it("startDate > endDate returns totalExpectedRevenueDollars = 0", async () => {
    const config = { ...BASE_CONFIG, startDate: "2024-01-10", endDate: "2024-01-08" };
    const result = await runSimulation(config);
    expect(result.totalExpectedRevenueDollars).toBe(0);
  });

  it("startDate > endDate returns totalActualRevenueDollars = 0", async () => {
    const config = { ...BASE_CONFIG, startDate: "2024-01-10", endDate: "2024-01-08" };
    const result = await runSimulation(config);
    expect(result.totalActualRevenueDollars).toBe(0);
  });

  it("startDate > endDate returns totalCycles = 0", async () => {
    const config = { ...BASE_CONFIG, startDate: "2024-01-10", endDate: "2024-01-08" };
    const result = await runSimulation(config);
    expect(result.totalCycles).toBe(0);
  });
});

// ---------------------------------------------------------------------------
// Forecast fails but optimize would succeed — day should record error, not throw
// ---------------------------------------------------------------------------

describe("runSimulation — callForecast failure", () => {
  it("forecast non-2xx: day records error status, simulation does not throw", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({
      ok: false,
      status: 503,
      text: () => Promise.resolve("Service Unavailable"),
    }));
    const result = await runSimulation(BASE_CONFIG);
    expect(result.days).toHaveLength(1);
    expect(result.days[0]?.solverStatus).toContain("error");
  });

  it("forecast failure leaves revenues at 0 for the day", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({
      ok: false,
      status: 500,
      text: () => Promise.resolve("Internal Server Error"),
    }));
    const result = await runSimulation(BASE_CONFIG);
    expect(result.days[0]?.expectedRevenueDollars).toBe(0);
    expect(result.days[0]?.actualRevenueDollars).toBe(0);
  });
});

// ---------------------------------------------------------------------------
// callForecast succeeds but callOptimize fails
// ---------------------------------------------------------------------------

describe("runSimulation — callOptimize failure after forecast success", () => {
  it("optimize non-2xx after forecast success: day records error status", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn((url: string) => {
        if ((url).includes("/forecast")) {
          return Promise.resolve({
            ok: true,
            json: () => Promise.resolve(makeForecastResponse("HB_NORTH")),
          });
        }
        // optimize fails
        return Promise.resolve({
          ok: false,
          status: 422,
          text: () => Promise.resolve("infeasible"),
        });
      })
    );

    const result = await runSimulation(BASE_CONFIG);
    expect(result.days).toHaveLength(1);
    expect(result.days[0]?.solverStatus).toContain("error");
  });

  it("optimize failure: simulation does not throw", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn((url: string) => {
        if ((url).includes("/forecast")) {
          return Promise.resolve({
            ok: true,
            json: () => Promise.resolve(makeForecastResponse("HB_NORTH")),
          });
        }
        return Promise.resolve({
          ok: false,
          status: 500,
          text: () => Promise.resolve("crash"),
        });
      })
    );
    // should not throw
    await expect(runSimulation(BASE_CONFIG)).resolves.toBeDefined();
  });

  it("optimize failure: revenues are 0, SoC unchanged from start", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn((url: string) => {
        if ((url).includes("/forecast")) {
          return Promise.resolve({
            ok: true,
            json: () => Promise.resolve(makeForecastResponse("HB_NORTH")),
          });
        }
        return Promise.resolve({
          ok: false,
          status: 500,
          text: () => Promise.resolve("crash"),
        });
      })
    );
    const result = await runSimulation(BASE_CONFIG);
    const day = result.days[0]!;
    expect(day.expectedRevenueDollars).toBe(0);
    expect(day.actualRevenueDollars).toBe(0);
    // SoC should be unchanged when no schedule was applied
    expect(day.socEndPct).toBeCloseTo(day.socStartPct);
  });
});

// ---------------------------------------------------------------------------
// Forecast returns no entry for the requested node — fallback to lmpToForecastIntervals
// ---------------------------------------------------------------------------

describe("runSimulation — forecast node fallback", () => {
  it("when forecast returns no matching node, runner uses lmpToForecastIntervals fallback", async () => {
    // Forecast returns a result for a DIFFERENT node
    const wrongNodeForecast = makeForecastResponse("SOME_OTHER_NODE");

    vi.stubGlobal(
      "fetch",
      vi.fn((url: string) => {
        if ((url).includes("/forecast")) {
          return Promise.resolve({
            ok: true,
            json: () => Promise.resolve(wrongNodeForecast),
          });
        }
        // Optimize succeeds — we can inspect what body it was called with
        return Promise.resolve({
          ok: true,
          json: () => Promise.resolve(makeOptimizeResponse()),
        });
      })
    );

    // Should not throw — fallback should be used silently
    const result = await runSimulation(BASE_CONFIG);
    expect(result.days).toHaveLength(1);
    // Simulation completes successfully with fallback
    expect(result.days[0]?.solverStatus).toBe("optimal");
  });

  it("fallback case still produces expected revenue from optimizer", async () => {
    const wrongNodeForecast = makeForecastResponse("WRONG_NODE");

    vi.stubGlobal(
      "fetch",
      vi.fn((url: string) => {
        if ((url).includes("/forecast")) {
          return Promise.resolve({
            ok: true,
            json: () => Promise.resolve(wrongNodeForecast),
          });
        }
        return Promise.resolve({
          ok: true,
          json: () => Promise.resolve(makeOptimizeResponse()),
        });
      })
    );

    const result = await runSimulation(BASE_CONFIG);
    // Optimizer returned non-zero expected revenue
    expect(result.totalExpectedRevenueDollars).not.toBe(0);
  });
});

// ---------------------------------------------------------------------------
// Multi-market simulation
// ---------------------------------------------------------------------------

describe("runSimulation — multi-market", () => {
  it("forecast is called once per market per day (2 markets = 2 forecast calls per day)", async () => {
    const mockFetch = vi.fn((url: string) => {
      if ((url).includes("/forecast")) {
        return Promise.resolve({
          ok: true,
          json: () => Promise.resolve(makeForecastResponse("HB_NORTH")),
        });
      }
      return Promise.resolve({
        ok: true,
        json: () => Promise.resolve(makeOptimizeResponse()),
      });
    });
    vi.stubGlobal("fetch", mockFetch);

    const config: SimConfig = {
      ...BASE_CONFIG,
      markets: ["DA_ENERGY", "RT_ENERGY"],
    };

    await runSimulation(config);

    const forecastCalls = mockFetch.mock.calls.filter(([url]) =>
      (url).includes("/forecast")
    );
    // 1 day * 2 markets = 2 forecast calls
    expect(forecastCalls).toHaveLength(2);
  });

  it("optimize is called once per day regardless of market count", async () => {
    const mockFetch = vi.fn((url: string) => {
      if ((url).includes("/forecast")) {
        return Promise.resolve({
          ok: true,
          json: () => Promise.resolve(makeForecastResponse("HB_NORTH")),
        });
      }
      return Promise.resolve({
        ok: true,
        json: () => Promise.resolve(makeOptimizeResponse()),
      });
    });
    vi.stubGlobal("fetch", mockFetch);

    const config: SimConfig = {
      ...BASE_CONFIG,
      markets: ["DA_ENERGY", "RT_ENERGY", "REG_UP"],
    };

    await runSimulation(config);

    const optimizeCalls = mockFetch.mock.calls.filter(([url]) =>
      (url).includes("/optimize")
    );
    // 1 day, 1 optimize call
    expect(optimizeCalls).toHaveLength(1);
  });

  it("multi-day multi-market: forecast calls = days * markets", async () => {
    const mockFetch = vi.fn((url: string) => {
      if ((url).includes("/forecast")) {
        return Promise.resolve({
          ok: true,
          json: () => Promise.resolve(makeForecastResponse("HB_NORTH")),
        });
      }
      return Promise.resolve({
        ok: true,
        json: () => Promise.resolve(makeOptimizeResponse()),
      });
    });
    vi.stubGlobal("fetch", mockFetch);

    const config: SimConfig = {
      ...BASE_CONFIG,
      startDate: "2024-01-08",
      endDate: "2024-01-10", // 3 days
      markets: ["DA_ENERGY", "RT_ENERGY"], // 2 markets
    };

    await runSimulation(config);

    const forecastCalls = mockFetch.mock.calls.filter(([url]) =>
      (url).includes("/forecast")
    );
    // 3 days * 2 markets = 6 forecast calls
    expect(forecastCalls).toHaveLength(6);
  });
});

// ---------------------------------------------------------------------------
// SoC continuity across days
// ---------------------------------------------------------------------------

describe("runSimulation — SoC continuity", () => {
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
        return Promise.resolve({
          ok: true,
          json: () => Promise.resolve(makeOptimizeResponse()),
        });
      })
    );
  });

  it("socStartPct of day N+1 equals socEndPct of day N", async () => {
    const config: SimConfig = {
      ...BASE_CONFIG,
      startDate: "2024-01-08",
      endDate: "2024-01-10",
    };
    const result = await runSimulation(config);
    for (let i = 0; i < result.days.length - 1; i++) {
      const day = result.days[i]!;
      const nextDay = result.days[i + 1]!;
      expect(nextDay.socStartPct).toBeCloseTo(day.socEndPct);
    }
  });
});
