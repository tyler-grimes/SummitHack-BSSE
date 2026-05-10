import type { ToolDefinition } from "./tool-registry.js";

const FORECASTING_URL =
  process.env["FORECASTING_SERVICE_URL"] ?? "http://localhost:8001";

export const runPriceForecast: ToolDefinition = {
  name: "run_price_forecast",
  description:
    "Call the forecasting service to generate probabilistic price predictions",
  inputSchema: {
    type: "object",
    properties: {
      iso: { type: "string" },
      nodes: { type: "array", items: { type: "string" } },
      market: {
        type: "string",
        enum: [
          "DA_ENERGY",
          "RT_ENERGY",
          "REG_UP",
          "REG_DOWN",
          "SPIN",
          "NONSPIN",
        ],
      },
      horizonHours: { type: "number" },
    },
    required: ["iso", "nodes", "market", "horizonHours"],
  },
  handler: async (input) => {
    const { iso, nodes, market, horizonHours } = input as {
      iso: string;
      nodes: string[];
      market: string;
      horizonHours: number;
    };
    const response = await fetch(`${FORECASTING_URL}/forecast`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ iso, nodes, market, horizon_hours: horizonHours }),
    });
    if (!response.ok)
      throw new Error(`Forecasting service error: ${response.status}`);
    return (await response.json()) as unknown;
  },
};

export const getForecastConfidence: ToolDefinition = {
  name: "get_forecast_confidence",
  description: "Get recent accuracy metrics for a forecasting model",
  inputSchema: {
    type: "object",
    properties: {
      modelId: { type: "string" },
    },
    required: ["modelId"],
  },
  handler: async (input) => {
    const { modelId } = input as { modelId: string };
    const response = await fetch(`${FORECASTING_URL}/confidence`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ model_id: modelId }),
    });
    if (!response.ok)
      throw new Error(`Forecasting service error: ${response.status}`);
    return (await response.json()) as unknown;
  },
};
