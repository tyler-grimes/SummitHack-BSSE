import type { ToolDefinition } from "./tool-registry.js";

const OPTIMIZATION_URL = process.env["OPTIMIZATION_SERVICE_URL"] ?? "http://localhost:8002";

export const getBatteryState: ToolDefinition = {
  name: "get_battery_state",
  description: "Get current battery state: SoC, available power, degradation cost",
  inputSchema: {
    type: "object",
    properties: {
      assetId: { type: "string" },
    },
    required: ["assetId"],
  },
  handler: (input) => {
    // TODO: query Redis (real-time state) or TimescaleDB (historical)
    return Promise.resolve({
      assetId: (input as { assetId: string }).assetId,
      socPct: 50,
      socMwh: 50,
      availableChargeMw: 25,
      availableDischargeMw: 25,
      tempC: 25,
      cycleCount: 100,
      degradationCostPerCycleDollars: 5.0,
      status: "stub",
    });
  },
};

export const solveDispatch: ToolDefinition = {
  name: "solve_dispatch",
  description: "Call CVXPY optimization solver to compute optimal battery dispatch schedule",
  inputSchema: {
    type: "object",
    properties: {
      assetId: { type: "string" },
      forecasts: { type: "object", description: "Price forecasts keyed by market" },
      horizonHours: { type: "number" },
      markets: { type: "array", items: { type: "string" } },
    },
    required: ["assetId", "forecasts", "horizonHours", "markets"],
  },
  handler: async (input) => {
    const response = await fetch(`${OPTIMIZATION_URL}/optimize`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(input),
    });
    if (!response.ok) throw new Error(`Optimization service error: ${response.status}`);
    const data: unknown = await response.json();
    return data;
  },
};

export const validateBids: ToolDefinition = {
  name: "validate_bids",
  description: "Validate a bid schedule against ISO constraints before submission",
  inputSchema: {
    type: "object",
    properties: {
      iso: { type: "string" },
      bids: { type: "array", items: { type: "object" } },
    },
    required: ["iso", "bids"],
  },
  handler: (_input) => {
    // TODO: ISO-specific constraint validation
    return Promise.resolve({ valid: true, violations: [], status: "stub" });
  },
};

export const checkRiskLimits: ToolDefinition = {
  name: "check_risk_limits",
  description: "Check proposed bids against current risk limits before execution",
  inputSchema: {
    type: "object",
    properties: {
      proposedBids: { type: "array", items: { type: "object" } },
      assetId: { type: "string" },
    },
    required: ["proposedBids", "assetId"],
  },
  handler: (_input) => {
    // TODO: query Redis for current exposure, check limits
    return Promise.resolve({ approved: true, violations: [], currentExposureMw: 0, status: "stub" });
  },
};
