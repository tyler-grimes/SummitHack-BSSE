import { describe, it, expect, vi, beforeEach } from "vitest";
import {
  callForecast,
  callOptimize,
  lmpToForecastIntervals,
} from "../src/services.js";
import type { LmpPoint } from "../src/synthetic-lmp.js";

// ---------------------------------------------------------------------------
// lmpToForecastIntervals
// ---------------------------------------------------------------------------

describe("lmpToForecastIntervals", () => {
  it("maps each LmpPoint to a ForecastInterval preserving timestamp", () => {
    const points: LmpPoint[] = [
      { timestamp: "2024-01-08T00:00:00.000Z", lmp: 40 },
      { timestamp: "2024-01-08T01:00:00.000Z", lmp: 60 },
    ];
    const result = lmpToForecastIntervals(points);
    expect(result[0]?.timestamp).toBe("2024-01-08T00:00:00.000Z");
    expect(result[1]?.timestamp).toBe("2024-01-08T01:00:00.000Z");
  });

  it("sets mean equal to lmp exactly", () => {
    const points: LmpPoint[] = [{ timestamp: "2024-01-08T00:00:00.000Z", lmp: 37.5 }];
    const [r] = lmpToForecastIntervals(points);
    expect(r?.mean).toBe(37.5);
  });

  it("sets p10 = lmp * 0.85 exactly", () => {
    const lmp = 40;
    const [r] = lmpToForecastIntervals([{ timestamp: "t", lmp }]);
    expect(r?.p10).toBeCloseTo(lmp * 0.85, 10);
  });

  it("sets p90 = lmp * 1.15 exactly", () => {
    const lmp = 40;
    const [r] = lmpToForecastIntervals([{ timestamp: "t", lmp }]);
    expect(r?.p90).toBeCloseTo(lmp * 1.15, 10);
  });

  it("p10 and p90 are symmetric around mean: mean = (p10+p90)/2", () => {
    const lmp = 100;
    const [r] = lmpToForecastIntervals([{ timestamp: "t", lmp }]);
    // (0.85 + 1.15) / 2 = 1.0, so (p10 + p90) / 2 === mean
    expect(((r?.p10 ?? 0) + (r?.p90 ?? 0)) / 2).toBeCloseTo(lmp, 10);
  });

  it("preserves output length equal to input length", () => {
    const points: LmpPoint[] = Array.from({ length: 24 }, (_, h) => ({
      timestamp: `2024-01-08T${String(h).padStart(2, "0")}:00:00.000Z`,
      lmp: 30 + h,
    }));
    expect(lmpToForecastIntervals(points)).toHaveLength(24);
  });

  it("empty array returns empty array", () => {
    expect(lmpToForecastIntervals([])).toEqual([]);
  });

  it("works with very small lmp (0.01 minimum boundary)", () => {
    const [r] = lmpToForecastIntervals([{ timestamp: "t", lmp: 0.01 }]);
    expect(r?.p10).toBeCloseTo(0.01 * 0.85, 10);
    expect(r?.p90).toBeCloseTo(0.01 * 1.15, 10);
  });

  it("timestamps are preserved exactly even with unusual strings", () => {
    const ts = "2024-12-31T23:00:00.000Z";
    const [r] = lmpToForecastIntervals([{ timestamp: ts, lmp: 50 }]);
    expect(r?.timestamp).toBe(ts);
  });
});

// ---------------------------------------------------------------------------
// callForecast
// ---------------------------------------------------------------------------

describe("callForecast", () => {
  beforeEach(() => {
    vi.stubGlobal("fetch", vi.fn());
  });

  it("POSTs to <url>/forecast", async () => {
    const mockFetch = vi.fn().mockResolvedValue({
      ok: true,
      json: () => Promise.resolve([]),
    });
    vi.stubGlobal("fetch", mockFetch);

    await callForecast("http://svc.test", "ERCOT", "HB_NORTH", "DA_ENERGY", 24);

    expect(mockFetch).toHaveBeenCalledOnce();
    const [calledUrl] = mockFetch.mock.calls[0] as [string, ...unknown[]];
    expect(calledUrl).toBe("http://svc.test/forecast");
  });

  it("uses POST method", async () => {
    const mockFetch = vi.fn().mockResolvedValue({
      ok: true,
      json: () => Promise.resolve([]),
    });
    vi.stubGlobal("fetch", mockFetch);

    await callForecast("http://svc.test", "ERCOT", "HB_NORTH", "DA_ENERGY", 24);

    const [, opts] = mockFetch.mock.calls[0] as [string, RequestInit];
    expect(opts.method).toBe("POST");
  });

  it("sends Content-Type: application/json", async () => {
    const mockFetch = vi.fn().mockResolvedValue({
      ok: true,
      json: () => Promise.resolve([]),
    });
    vi.stubGlobal("fetch", mockFetch);

    await callForecast("http://svc.test", "ERCOT", "HB_NORTH", "DA_ENERGY", 24);

    const [, opts] = mockFetch.mock.calls[0] as [string, RequestInit];
    const headers = opts.headers as Record<string, string>;
    expect(headers["Content-Type"]).toBe("application/json");
  });

  it("sends iso, node in nodes array, market, and horizon_hours snake_case in body", async () => {
    const mockFetch = vi.fn().mockResolvedValue({
      ok: true,
      json: () => Promise.resolve([]),
    });
    vi.stubGlobal("fetch", mockFetch);

    await callForecast("http://svc.test", "CAISO", "SP15", "RT_ENERGY", 48);

    const [, opts] = mockFetch.mock.calls[0] as [string, RequestInit];
    const body = JSON.parse(opts.body as string) as Record<string, unknown>;
    expect(body["iso"]).toBe("CAISO");
    expect(body["nodes"]).toEqual(["SP15"]);
    expect(body["market"]).toBe("RT_ENERGY");
    expect(body["horizon_hours"]).toBe(48);
    // Must use snake_case key, not camelCase
    expect(body).not.toHaveProperty("horizonHours");
  });

  it("returns parsed JSON array on success", async () => {
    const payload = [{ iso: "ERCOT", node: "HB_NORTH", market: "DA_ENERGY", intervals: [], model_id: "m1", confidence: 0.9 }];
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({
      ok: true,
      json: () => Promise.resolve(payload),
    }));

    const result = await callForecast("http://svc.test", "ERCOT", "HB_NORTH", "DA_ENERGY", 24);
    expect(result).toEqual(payload);
  });

  it("throws with status code on non-2xx response", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({
      ok: false,
      status: 503,
      text: () => Promise.resolve("Service Unavailable"),
    }));

    await expect(
      callForecast("http://svc.test", "ERCOT", "HB_NORTH", "DA_ENERGY", 24)
    ).rejects.toThrow("503");
  });

  it("throws with response body text on non-2xx", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({
      ok: false,
      status: 422,
      text: () => Promise.resolve("invalid node"),
    }));

    await expect(
      callForecast("http://svc.test", "ERCOT", "HB_NORTH", "DA_ENERGY", 24)
    ).rejects.toThrow("invalid node");
  });

  it("throws on 404 not found", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({
      ok: false,
      status: 404,
      text: () => Promise.resolve("not found"),
    }));

    await expect(
      callForecast("http://svc.test", "ERCOT", "HB_NORTH", "DA_ENERGY", 24)
    ).rejects.toThrow();
  });
});

// ---------------------------------------------------------------------------
// callOptimize
// ---------------------------------------------------------------------------

describe("callOptimize", () => {
  beforeEach(() => {
    vi.stubGlobal("fetch", vi.fn());
  });

  it("POSTs to <url>/optimize", async () => {
    const mockFetch = vi.fn().mockResolvedValue({
      ok: true,
      json: () => Promise.resolve({ asset_id: "X", intervals: [], total_expected_revenue_dollars: 0, solver_status: "optimal" }),
    });
    vi.stubGlobal("fetch", mockFetch);

    await callOptimize("http://opt.test", "BESS-001", {}, 24, ["DA_ENERGY"]);

    const [calledUrl] = mockFetch.mock.calls[0] as [string, ...unknown[]];
    expect(calledUrl).toBe("http://opt.test/optimize");
  });

  it("uses POST method", async () => {
    const mockFetch = vi.fn().mockResolvedValue({
      ok: true,
      json: () => Promise.resolve({ asset_id: "X", intervals: [], total_expected_revenue_dollars: 0, solver_status: "optimal" }),
    });
    vi.stubGlobal("fetch", mockFetch);

    await callOptimize("http://opt.test", "BESS-001", {}, 24, ["DA_ENERGY"]);

    const [, opts] = mockFetch.mock.calls[0] as [string, RequestInit];
    expect(opts.method).toBe("POST");
  });

  it("sends asset_id as snake_case in body", async () => {
    const mockFetch = vi.fn().mockResolvedValue({
      ok: true,
      json: () => Promise.resolve({ asset_id: "BESS-007", intervals: [], total_expected_revenue_dollars: 0, solver_status: "optimal" }),
    });
    vi.stubGlobal("fetch", mockFetch);

    await callOptimize("http://opt.test", "BESS-007", {}, 24, ["DA_ENERGY"]);

    const [, opts] = mockFetch.mock.calls[0] as [string, RequestInit];
    const body = JSON.parse(opts.body as string) as Record<string, unknown>;
    expect(body["asset_id"]).toBe("BESS-007");
    // Must not use camelCase key
    expect(body).not.toHaveProperty("assetId");
  });

  it("sends horizon_hours as snake_case in body", async () => {
    const mockFetch = vi.fn().mockResolvedValue({
      ok: true,
      json: () => Promise.resolve({ asset_id: "X", intervals: [], total_expected_revenue_dollars: 0, solver_status: "optimal" }),
    });
    vi.stubGlobal("fetch", mockFetch);

    await callOptimize("http://opt.test", "BESS-001", {}, 48, ["DA_ENERGY"]);

    const [, opts] = mockFetch.mock.calls[0] as [string, RequestInit];
    const body = JSON.parse(opts.body as string) as Record<string, unknown>;
    expect(body["horizon_hours"]).toBe(48);
    expect(body).not.toHaveProperty("horizonHours");
  });

  it("sends markets array in body", async () => {
    const mockFetch = vi.fn().mockResolvedValue({
      ok: true,
      json: () => Promise.resolve({ asset_id: "X", intervals: [], total_expected_revenue_dollars: 0, solver_status: "optimal" }),
    });
    vi.stubGlobal("fetch", mockFetch);

    await callOptimize("http://opt.test", "BESS-001", {}, 24, ["DA_ENERGY", "RT_ENERGY"]);

    const [, opts] = mockFetch.mock.calls[0] as [string, RequestInit];
    const body = JSON.parse(opts.body as string) as Record<string, unknown>;
    expect(body["markets"]).toEqual(["DA_ENERGY", "RT_ENERGY"]);
  });

  it("sends forecastsByMarket as forecasts key in body", async () => {
    const forecastsByMarket = {
      DA_ENERGY: [{ timestamp: "t", mean: 35, p10: 29.75, p90: 40.25 }],
    };
    const mockFetch = vi.fn().mockResolvedValue({
      ok: true,
      json: () => Promise.resolve({ asset_id: "X", intervals: [], total_expected_revenue_dollars: 0, solver_status: "optimal" }),
    });
    vi.stubGlobal("fetch", mockFetch);

    await callOptimize("http://opt.test", "BESS-001", forecastsByMarket, 24, ["DA_ENERGY"]);

    const [, opts] = mockFetch.mock.calls[0] as [string, RequestInit];
    const body = JSON.parse(opts.body as string) as Record<string, unknown>;
    expect(body["forecasts"]).toEqual(forecastsByMarket);
  });

  it("returns parsed OptimizeResult on success", async () => {
    const payload = {
      asset_id: "BESS-001",
      intervals: [],
      total_expected_revenue_dollars: 500,
      solver_status: "optimal",
    };
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({
      ok: true,
      json: () => Promise.resolve(payload),
    }));

    const result = await callOptimize("http://opt.test", "BESS-001", {}, 24, ["DA_ENERGY"]);
    expect(result).toEqual(payload);
  });

  it("throws with status code on non-2xx response", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({
      ok: false,
      status: 500,
      text: () => Promise.resolve("Internal Server Error"),
    }));

    await expect(
      callOptimize("http://opt.test", "BESS-001", {}, 24, ["DA_ENERGY"])
    ).rejects.toThrow("500");
  });

  it("throws with response body text on non-2xx", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({
      ok: false,
      status: 400,
      text: () => Promise.resolve("infeasible problem"),
    }));

    await expect(
      callOptimize("http://opt.test", "BESS-001", {}, 24, ["DA_ENERGY"])
    ).rejects.toThrow("infeasible problem");
  });
});
