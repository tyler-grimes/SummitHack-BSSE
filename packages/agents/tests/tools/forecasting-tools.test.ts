import { describe, it, expect, vi, beforeEach } from "vitest";
import { runPriceForecast, getForecastConfidence } from "../../src/tools/forecasting-tools.js";

// Helper to build a minimal Response-like object
function makeResponse(status: number, body: unknown): Response {
  return {
    ok: status >= 200 && status < 300,
    status,
    json: () => Promise.resolve(body),
  } as unknown as Response;
}

describe("forecasting-tools", () => {
  let mockFetch: ReturnType<typeof vi.fn>;

  beforeEach(() => {
    mockFetch = vi.fn();
    vi.stubGlobal("fetch", mockFetch);
  });

  // --- run_price_forecast ---

  describe("run_price_forecast", () => {
    it("sends POST to /forecast with snake_case horizon_hours (not horizonHours)", async () => {
      mockFetch.mockResolvedValue(makeResponse(200, { forecasts: [] }));

      await runPriceForecast.handler({
        iso: "ERCOT",
        nodes: ["HB_NORTH"],
        market: "DA_ENERGY",
        horizonHours: 24,
      });

      expect(mockFetch).toHaveBeenCalledOnce();
      const [url, init] = mockFetch.mock.calls[0] as [string, RequestInit];
      expect(url).toMatch(/\/forecast$/);
      expect(init.method).toBe("POST");

      const sentBody = JSON.parse(init.body as string) as Record<string, unknown>;
      // snake_case field must be present
      expect(sentBody).toHaveProperty("horizon_hours", 24);
      // camelCase must NOT appear in the wire body
      expect(sentBody).not.toHaveProperty("horizonHours");
      // other fields forwarded unchanged
      expect(sentBody).toMatchObject({ iso: "ERCOT", nodes: ["HB_NORTH"], market: "DA_ENERGY" });
    });

    it("throws on non-2xx response", async () => {
      mockFetch.mockResolvedValue(makeResponse(503, { error: "unavailable" }));

      await expect(
        runPriceForecast.handler({ iso: "PJM", nodes: ["AEP-DAYTON"], market: "RT_ENERGY", horizonHours: 4 })
      ).rejects.toThrow("Forecasting service error: 503");
    });

    it("throws on 4xx client error", async () => {
      mockFetch.mockResolvedValue(makeResponse(400, { error: "bad request" }));

      await expect(
        runPriceForecast.handler({ iso: "CAISO", nodes: ["TH_NP15_GEN-APND"], market: "DA_ENERGY", horizonHours: 8 })
      ).rejects.toThrow("Forecasting service error: 400");
    });

    it("returns the parsed JSON response body on success", async () => {
      const payload = { forecasts: [{ node: "HB_NORTH", p50: 42.5 }] };
      mockFetch.mockResolvedValue(makeResponse(200, payload));

      const result = await runPriceForecast.handler({
        iso: "ERCOT",
        nodes: ["HB_NORTH"],
        market: "DA_ENERGY",
        horizonHours: 12,
      });

      expect(result).toEqual(payload);
    });
  });

  // --- get_forecast_confidence ---

  describe("get_forecast_confidence", () => {
    it("sends model_id (snake_case) in POST body, not modelId", async () => {
      mockFetch.mockResolvedValue(makeResponse(200, { accuracy: 0.87 }));

      await getForecastConfidence.handler({ modelId: "ercot-da-v3" });

      expect(mockFetch).toHaveBeenCalledOnce();
      const [url, init] = mockFetch.mock.calls[0] as [string, RequestInit];
      expect(url).toMatch(/\/confidence$/);
      expect(init.method).toBe("POST");

      const sentBody = JSON.parse(init.body as string) as Record<string, unknown>;
      expect(sentBody).toHaveProperty("model_id", "ercot-da-v3");
      expect(sentBody).not.toHaveProperty("modelId");
    });

    it("throws on non-2xx response", async () => {
      mockFetch.mockResolvedValue(makeResponse(404, { error: "model not found" }));

      await expect(
        getForecastConfidence.handler({ modelId: "nonexistent-model" })
      ).rejects.toThrow("Forecasting service error: 404");
    });

    it("returns the parsed response body on success", async () => {
      const payload = { accuracy: 0.92, rmse: 3.14, model_id: "pjm-rt-v1" };
      mockFetch.mockResolvedValue(makeResponse(200, payload));

      const result = await getForecastConfidence.handler({ modelId: "pjm-rt-v1" });
      expect(result).toEqual(payload);
    });
  });
});
