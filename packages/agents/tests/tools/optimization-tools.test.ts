import { describe, it, expect, vi, beforeEach } from "vitest";
import {
  getBatteryState,
  solveDispatch,
  validateBids,
  checkRiskLimits,
} from "../../src/tools/optimization-tools.js";

// Mock Redis before importing anything that might trigger singleton creation
const mockRedisGet = vi.fn();
vi.mock("../../src/redis/client.js", () => ({
  getRedisClient: vi.fn(() => ({ get: mockRedisGet })),
}));

function makeResponse(status: number, body: unknown): Response {
  return {
    ok: status >= 200 && status < 300,
    status,
    json: () => Promise.resolve(body),
  } as unknown as Response;
}

const BASE_BATTERY: Record<string, unknown> = {
  asset_id: "bess-01",
  capacity_mwh: 100,
  max_charge_mw: 25,
  max_discharge_mw: 25,
  eta_charge: 0.95,
  eta_discharge: 0.95,
  soc_min_pct: 0.1,
  soc_max_pct: 0.9,
  initial_soc_pct: 0.5,
  degradation_per_mwh: 0.8,
};

describe("optimization-tools", () => {
  let mockFetch: ReturnType<typeof vi.fn>;

  beforeEach(() => {
    mockFetch = vi.fn();
    vi.stubGlobal("fetch", mockFetch);
    // Default: Redis key not present
    mockRedisGet.mockResolvedValue(null);
  });

  // --- get_battery_state ---

  describe("get_battery_state", () => {
    it("calls GET /battery/{assetId} on the optimization service", async () => {
      mockFetch.mockResolvedValue(makeResponse(200, BASE_BATTERY));

      await getBatteryState.handler({ assetId: "bess-01" });

      expect(mockFetch).toHaveBeenCalledOnce();
      const [url, init] = mockFetch.mock.calls[0] as [string, RequestInit | undefined];
      expect(url).toMatch(/\/battery\/bess-01$/);
      // GET does not supply a body
      expect(init?.method).toBeUndefined();
    });

    it("throws when optimization service returns non-2xx", async () => {
      mockFetch.mockResolvedValue(makeResponse(404, { error: "not found" }));

      await expect(getBatteryState.handler({ assetId: "missing-asset" })).rejects.toThrow(
        /Optimization service error: 404/
      );
    });

    it("uses Redis SoC when key is present, overrides initial_soc_pct", async () => {
      mockFetch.mockResolvedValue(makeResponse(200, { ...BASE_BATTERY, initial_soc_pct: 0.5 }));
      // Redis returns SoC = 0.8 (80%)
      mockRedisGet.mockResolvedValue("0.8");

      const result = (await getBatteryState.handler({ assetId: "bess-01" })) as Record<string, unknown>;

      expect(result["socPct"]).toBe(0.8);
      expect(result["socMwh"]).toBeCloseTo(80, 5); // 0.8 * 100 mwh
    });

    it("falls back to initial_soc_pct when Redis key is missing (null)", async () => {
      mockFetch.mockResolvedValue(makeResponse(200, { ...BASE_BATTERY, initial_soc_pct: 0.5 }));
      mockRedisGet.mockResolvedValue(null);

      const result = (await getBatteryState.handler({ assetId: "bess-01" })) as Record<string, unknown>;

      expect(result["socPct"]).toBe(0.5);
      expect(result["socMwh"]).toBeCloseTo(50, 5);
    });

    it("clamps availableChargeMw to >= 0 when battery is nearly full", async () => {
      // SoC = 0.9 = soc_max_pct → headroom is 0, so availableChargeMw should be 0
      mockFetch.mockResolvedValue(makeResponse(200, { ...BASE_BATTERY, initial_soc_pct: 0.9 }));
      mockRedisGet.mockResolvedValue(null);

      const result = (await getBatteryState.handler({ assetId: "bess-01" })) as Record<string, unknown>;

      expect(result["availableChargeMw"]).toBeGreaterThanOrEqual(0);
    });

    it("clamps availableDischargeMw to >= 0 when battery is nearly empty", async () => {
      // SoC = 0.1 = soc_min_pct → no energy to discharge
      mockFetch.mockResolvedValue(makeResponse(200, { ...BASE_BATTERY, initial_soc_pct: 0.1 }));
      mockRedisGet.mockResolvedValue(null);

      const result = (await getBatteryState.handler({ assetId: "bess-01" })) as Record<string, unknown>;

      expect(result["availableDischargeMw"]).toBeGreaterThanOrEqual(0);
    });

    it("clamps availableChargeMw below zero (Redis SoC above soc_max_pct edge case)", async () => {
      // Overcharge scenario: SoC from Redis = 0.95, above soc_max_pct 0.9
      // (socMax - socPct) * capacity = (0.9 - 0.95) * 100 = -5  → must be clamped to 0
      mockFetch.mockResolvedValue(makeResponse(200, { ...BASE_BATTERY }));
      mockRedisGet.mockResolvedValue("0.95");

      const result = (await getBatteryState.handler({ assetId: "bess-01" })) as Record<string, unknown>;

      expect(result["availableChargeMw"]).toBe(0);
    });
  });

  // --- solve_dispatch ---

  describe("solve_dispatch", () => {
    it("sends snake_case body (asset_id, horizon_hours) to /optimize", async () => {
      const dispatchResult = { schedule: [] };
      mockFetch.mockResolvedValue(makeResponse(200, dispatchResult));

      const forecasts = { DA_ENERGY: [{ hour: 0, p50: 45.0 }] };
      await solveDispatch.handler({
        assetId: "bess-01",
        forecasts,
        horizonHours: 24,
        markets: ["DA_ENERGY"],
      });

      const [url, init] = mockFetch.mock.calls[0] as [string, RequestInit];
      expect(url).toMatch(/\/optimize$/);
      expect(init.method).toBe("POST");

      const body = JSON.parse(init.body as string) as Record<string, unknown>;
      expect(body).toHaveProperty("asset_id", "bess-01");
      expect(body).toHaveProperty("horizon_hours", 24);
      expect(body).not.toHaveProperty("assetId");
      expect(body).not.toHaveProperty("horizonHours");
      expect(body).toHaveProperty("markets", ["DA_ENERGY"]);
      expect(body).toHaveProperty("forecasts", forecasts);
    });

    it("throws on non-2xx response from optimization service", async () => {
      mockFetch.mockResolvedValue(makeResponse(500, { error: "solver error" }));

      await expect(
        solveDispatch.handler({
          assetId: "bess-01",
          forecasts: {},
          horizonHours: 4,
          markets: ["DA_ENERGY"],
        })
      ).rejects.toThrow("Optimization service error: 500");
    });
  });

  // --- validate_bids ---

  describe("validate_bids", () => {
    it("valid bids return { valid: true, violations: [] }", async () => {
      const result = (await validateBids.handler({
        iso: "ERCOT",
        bids: [
          { charge_mw: 10, discharge_mw: 0, price: 50 },
          { charge_mw: 0, discharge_mw: 15, price: 200 },
        ],
      })) as { valid: boolean; violations: string[] };

      expect(result.valid).toBe(true);
      expect(result.violations).toHaveLength(0);
    });

    it("negative charge_mw produces a violation", async () => {
      const result = (await validateBids.handler({
        iso: "ERCOT",
        bids: [{ charge_mw: -5, discharge_mw: 0, price: 50 }],
      })) as { valid: boolean; violations: string[] };

      expect(result.valid).toBe(false);
      expect(result.violations).toHaveLength(1);
      expect(result.violations[0]).toMatch(/negative charge_mw/);
    });

    it("negative discharge_mw produces a violation", async () => {
      const result = (await validateBids.handler({
        iso: "ERCOT",
        bids: [{ charge_mw: 0, discharge_mw: -3, price: 50 }],
      })) as { valid: boolean; violations: string[] };

      expect(result.valid).toBe(false);
      expect(result.violations).toHaveLength(1);
      expect(result.violations[0]).toMatch(/negative discharge_mw/);
    });

    it("price above ERCOT cap ($9000) produces violation", async () => {
      const result = (await validateBids.handler({
        iso: "ERCOT",
        bids: [{ charge_mw: 0, discharge_mw: 10, price: 9001 }],
      })) as { valid: boolean; violations: string[] };

      expect(result.valid).toBe(false);
      expect(result.violations[0]).toMatch(/9001/);
      expect(result.violations[0]).toMatch(/ERCOT/);
    });

    it("price above PJM cap ($2000) produces violation", async () => {
      const result = (await validateBids.handler({
        iso: "PJM",
        bids: [{ charge_mw: 0, discharge_mw: 10, price: 2500 }],
      })) as { valid: boolean; violations: string[] };

      expect(result.valid).toBe(false);
      expect(result.violations[0]).toMatch(/2500/);
    });

    it("price within ERCOT cap is accepted", async () => {
      const result = (await validateBids.handler({
        iso: "ERCOT",
        bids: [{ charge_mw: 0, discharge_mw: 10, price: 8999 }],
      })) as { valid: boolean; violations: string[] };

      expect(result.valid).toBe(true);
      expect(result.violations).toHaveLength(0);
    });

    it("price at exactly the cap boundary is accepted", async () => {
      const result = (await validateBids.handler({
        iso: "PJM",
        bids: [{ charge_mw: 0, discharge_mw: 10, price: 2000 }],
      })) as { valid: boolean; violations: string[] };

      expect(result.valid).toBe(true);
    });

    it("unknown ISO falls back to default caps and does not throw", async () => {
      const result = (await validateBids.handler({
        iso: "UNKNOWN_ISO",
        bids: [{ charge_mw: 5, discharge_mw: 0, price: 500 }],
      })) as { valid: boolean; violations: string[] };

      // Should not throw; should return a valid/invalid result
      expect(typeof result.valid).toBe("boolean");
      expect(Array.isArray(result.violations)).toBe(true);
    });

    it("price below ISO minimum (negative floor) produces violation", async () => {
      // ERCOT min is -250; price -300 is below floor
      const result = (await validateBids.handler({
        iso: "ERCOT",
        bids: [{ charge_mw: 10, discharge_mw: 0, price: -300 }],
      })) as { valid: boolean; violations: string[] };

      expect(result.valid).toBe(false);
      expect(result.violations[0]).toMatch(/-300/);
    });

    it("iso matching is case-insensitive (ercot → ERCOT caps)", async () => {
      const result = (await validateBids.handler({
        iso: "ercot",
        bids: [{ charge_mw: 0, discharge_mw: 10, price: 9001 }],
      })) as { valid: boolean; violations: string[] };

      expect(result.valid).toBe(false);
    });

    it("missing price field does not produce a price violation", async () => {
      const result = (await validateBids.handler({
        iso: "ERCOT",
        bids: [{ charge_mw: 5 }],
      })) as { valid: boolean; violations: string[] };

      expect(result.valid).toBe(true);
      expect(result.violations).toHaveLength(0);
    });
  });

  // --- check_risk_limits ---

  describe("check_risk_limits", () => {
    beforeEach(() => {
      // Reset env vars between tests
      delete process.env["RISK_MAX_DAILY_REVENUE_DOLLARS"];
      delete process.env["RISK_MAX_POSITION_MW"];
    });

    it("within limits returns { approved: true, violations: [] }", async () => {
      mockRedisGet.mockResolvedValue("0"); // current exposure = $0

      const result = (await checkRiskLimits.handler({
        assetId: "bess-01",
        proposedBids: [
          { charge_mw: 10, discharge_mw: 0, expected_revenue_dollars: 1000 },
        ],
      })) as { approved: boolean; violations: string[] };

      expect(result.approved).toBe(true);
      expect(result.violations).toHaveLength(0);
    });

    it("daily revenue exceeds limit returns violation and approved: false", async () => {
      process.env["RISK_MAX_DAILY_REVENUE_DOLLARS"] = "5000";
      mockRedisGet.mockResolvedValue("4000"); // current exposure $4000

      const result = (await checkRiskLimits.handler({
        assetId: "bess-01",
        proposedBids: [
          { expected_revenue_dollars: 2000 }, // total = $6000 > $5000
        ],
      })) as { approved: boolean; violations: string[] };

      expect(result.approved).toBe(false);
      expect(result.violations).toHaveLength(1);
      expect(result.violations[0]).toMatch(/Daily revenue limit exceeded/);
    });

    it("peak MW exceeds limit returns violation and approved: false", async () => {
      process.env["RISK_MAX_POSITION_MW"] = "20";
      mockRedisGet.mockResolvedValue("0");

      const result = (await checkRiskLimits.handler({
        assetId: "bess-01",
        proposedBids: [
          { charge_mw: 25, discharge_mw: 0, expected_revenue_dollars: 100 }, // 25 > 20
        ],
      })) as { approved: boolean; violations: string[] };

      expect(result.approved).toBe(false);
      expect(result.violations.some((v) => v.match(/Peak position/))).toBe(true);
    });

    it("reads RISK_MAX_DAILY_REVENUE_DOLLARS from env var", async () => {
      process.env["RISK_MAX_DAILY_REVENUE_DOLLARS"] = "100";
      mockRedisGet.mockResolvedValue("0");

      const result = (await checkRiskLimits.handler({
        assetId: "bess-01",
        proposedBids: [{ expected_revenue_dollars: 101 }],
      })) as { approved: boolean; maxDailyRevenueDollars: number };

      expect(result.maxDailyRevenueDollars).toBe(100);
      expect(result.approved).toBe(false);
    });

    it("Redis failure (get throws) falls back to 0 exposure and does not crash", async () => {
      mockRedisGet.mockRejectedValue(new Error("Redis connection refused"));

      // Should not throw; currentExposure defaults to 0
      const result = (await checkRiskLimits.handler({
        assetId: "bess-01",
        proposedBids: [{ expected_revenue_dollars: 100 }],
      })) as { approved: boolean; currentExposureDollars: number };

      expect(result.currentExposureDollars).toBe(0);
      expect(result.approved).toBe(true); // 100 < default limit 50000
    });

    it("returns currentExposureDollars and proposedRevenueDollars in response", async () => {
      mockRedisGet.mockResolvedValue("1500");

      const result = (await checkRiskLimits.handler({
        assetId: "bess-01",
        proposedBids: [{ expected_revenue_dollars: 500 }],
      })) as { currentExposureDollars: number; proposedRevenueDollars: number };

      expect(result.currentExposureDollars).toBe(1500);
      expect(result.proposedRevenueDollars).toBe(500);
    });

    it("both revenue and MW violations can appear simultaneously", async () => {
      process.env["RISK_MAX_DAILY_REVENUE_DOLLARS"] = "100";
      process.env["RISK_MAX_POSITION_MW"] = "5";
      mockRedisGet.mockResolvedValue("200");

      const result = (await checkRiskLimits.handler({
        assetId: "bess-01",
        proposedBids: [
          { charge_mw: 10, expected_revenue_dollars: 50 },
        ],
      })) as { approved: boolean; violations: string[] };

      expect(result.approved).toBe(false);
      expect(result.violations.length).toBeGreaterThanOrEqual(2);
    });
  });
});
