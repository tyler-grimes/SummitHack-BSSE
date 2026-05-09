import type { ToolDefinition } from "./tool-registry.js";

const FORECASTING_URL = process.env["FORECASTING_SERVICE_URL"] ?? "http://localhost:8001";

export const runPriceForecast: ToolDefinition = {
  name: "run_price_forecast",
  description: "Call the forecasting service to generate probabilistic price predictions",
  inputSchema: {
    type: "object",
    properties: {
      iso: { type: "string" },
      nodes: { type: "array", items: { type: "string" } },
      market: { type: "string", enum: ["DA_ENERGY", "RT_ENERGY", "REG_UP", "REG_DOWN", "SPIN", "NONSPIN"] },
      horizonHours: { type: "number" },
    },
    required: ["iso", "nodes", "market", "horizonHours"],
  },
  handler: async (input) => {
    const response = await fetch(`${FORECASTING_URL}/forecast`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(input),
    });
    if (!response.ok) throw new Error(`Forecasting service error: ${response.status}`);
    const data: unknown = await response.json();
    return data;
  },
};

export const getForecastConfidence: ToolDefinition = {
  name: "get_forecast_confidence",
  description: "Get recent accuracy metrics for a forecasting model",
  inputSchema: {
    type: "object",
    properties: {
      modelId: { type: "string" },
      recentDays: { type: "number", default: 7 },
    },
    required: ["modelId"],
  },
  handler: async (input) => {
    const response = await fetch(`${FORECASTING_URL}/confidence`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(input),
    });
    if (!response.ok) throw new Error(`Forecasting service error: ${response.status}`);
    const data: unknown = await response.json();
    return data;
  },
};
