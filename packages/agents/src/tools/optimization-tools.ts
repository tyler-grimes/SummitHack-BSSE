import type { ToolDefinition } from "./tool-registry.js";
import { getRedisClient } from "../redis/client.js";

const OPTIMIZATION_URL =
  process.env["OPTIMIZATION_SERVICE_URL"] ?? "http://localhost:8002";

interface BatteryConfig {
  asset_id: string;
  capacity_mwh: number;
  max_charge_mw: number;
  max_discharge_mw: number;
  eta_charge: number;
  eta_discharge: number;
  soc_min_pct: number;
  soc_max_pct: number;
  initial_soc_pct: number;
  degradation_per_mwh: number;
}

const ISO_PRICE_CAPS: Record<string, { min: number; max: number }> = {
  ERCOT: { min: -250, max: 9000 },
  PJM: { min: -500, max: 2000 },
  CAISO: { min: -150, max: 1000 },
  ISONE: { min: -150, max: 1000 },
  MISO: { min: -500, max: 2000 },
  NYISO: { min: -500, max: 1000 },
  SPP: { min: -500, max: 2000 },
};

export const getBatteryState: ToolDefinition = {
  name: "get_battery_state",
  description:
    "Get current battery state: SoC, available power, degradation cost",
  inputSchema: {
    type: "object",
    properties: {
      assetId: { type: "string" },
    },
    required: ["assetId"],
  },
  handler: async (input) => {
    const { assetId } = input as { assetId: string };

    const response = await fetch(`${OPTIMIZATION_URL}/battery/${assetId}`);
    if (!response.ok)
      throw new Error(
        `Optimization service error: ${response.status} for asset ${assetId}`
      );
    const params = (await response.json()) as BatteryConfig;

    // Real-time SoC from Redis; falls back to initial_soc_pct on first run
    const redis = getRedisClient();
    const socRaw = await redis.get(`bess:soc:${assetId}`).catch(() => null);
    const socPct = socRaw !== null ? parseFloat(socRaw) : params.initial_soc_pct;
    const socMwh = socPct * params.capacity_mwh;

    const availableChargeMw = Math.min(
      params.max_charge_mw,
      (params.soc_max_pct - socPct) * params.capacity_mwh
    );
    const availableDischargeMw = Math.min(
      params.max_discharge_mw,
      (socPct - params.soc_min_pct) * params.capacity_mwh
    );

    return {
      assetId,
      socPct,
      socMwh,
      capacityMwh: params.capacity_mwh,
      availableChargeMw: Math.max(0, availableChargeMw),
      availableDischargeMw: Math.max(0, availableDischargeMw),
      degradationCostPerMwh: params.degradation_per_mwh,
    };
  },
};

export const solveDispatch: ToolDefinition = {
  name: "solve_dispatch",
  description:
    "Call CVXPY optimization solver to compute optimal battery dispatch schedule",
  inputSchema: {
    type: "object",
    properties: {
      assetId: { type: "string" },
      forecasts: {
        type: "object",
        description: "Price forecasts keyed by market name",
      },
      horizonHours: { type: "number" },
      markets: { type: "array", items: { type: "string" } },
    },
    required: ["assetId", "forecasts", "horizonHours", "markets"],
  },
  handler: async (input) => {
    const { assetId, forecasts, horizonHours, markets } = input as {
      assetId: string;
      forecasts: Record<string, unknown>;
      horizonHours: number;
      markets: string[];
    };
    const response = await fetch(`${OPTIMIZATION_URL}/optimize`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        asset_id: assetId,
        forecasts,
        horizon_hours: horizonHours,
        markets,
      }),
    });
    if (!response.ok)
      throw new Error(`Optimization service error: ${response.status}`);
    return (await response.json()) as unknown;
  },
};

export const validateBids: ToolDefinition = {
  name: "validate_bids",
  description:
    "Validate a bid schedule against ISO constraints before submission",
  inputSchema: {
    type: "object",
    properties: {
      iso: { type: "string" },
      bids: { type: "array", items: { type: "object" } },
    },
    required: ["iso", "bids"],
  },
  handler: (input) => {
    const { iso, bids } = input as {
      iso: string;
      bids: Array<{
        charge_mw?: number;
        discharge_mw?: number;
        price?: number;
        expected_revenue_dollars?: number;
      }>;
    };

    const caps = ISO_PRICE_CAPS[iso.toUpperCase()] ?? { min: -500, max: 9000 };
    const violations: string[] = [];

    for (let i = 0; i < bids.length; i++) {
      const bid = bids[i];
      if (bid === undefined) continue;
      if ((bid.charge_mw ?? 0) < -1e-6)
        violations.push(`Interval ${i}: negative charge_mw ${bid.charge_mw}`);
      if ((bid.discharge_mw ?? 0) < -1e-6)
        violations.push(
          `Interval ${i}: negative discharge_mw ${bid.discharge_mw}`
        );
      if (
        bid.price !== undefined &&
        (bid.price < caps.min || bid.price > caps.max)
      ) {
        violations.push(
          `Interval ${i}: price ${bid.price} outside ${iso} bounds [${caps.min}, ${caps.max}]`
        );
      }
    }

    return Promise.resolve({ valid: violations.length === 0, violations, iso });
  },
};

export const checkRiskLimits: ToolDefinition = {
  name: "check_risk_limits",
  description:
    "Check proposed bids against current risk limits before execution",
  inputSchema: {
    type: "object",
    properties: {
      proposedBids: { type: "array", items: { type: "object" } },
      assetId: { type: "string" },
    },
    required: ["proposedBids", "assetId"],
  },
  handler: async (input) => {
    const { proposedBids, assetId } = input as {
      proposedBids: Array<{
        charge_mw?: number;
        discharge_mw?: number;
        expected_revenue_dollars?: number;
      }>;
      assetId: string;
    };

    const maxDailyRevenue = parseFloat(
      process.env["RISK_MAX_DAILY_REVENUE_DOLLARS"] ?? "50000"
    );
    const maxPositionMw = parseFloat(
      process.env["RISK_MAX_POSITION_MW"] ?? "100"
    );

    const redis = getRedisClient();
    const exposureRaw = await redis
      .get(`risk:daily_exposure:${assetId}`)
      .catch(() => null);
    const currentExposure =
      exposureRaw !== null ? parseFloat(exposureRaw) : 0;

    const proposedRevenue = proposedBids.reduce(
      (sum, b) => sum + (b.expected_revenue_dollars ?? 0),
      0
    );
    const peakPositionMw = proposedBids.reduce(
      (max, b) => Math.max(max, b.charge_mw ?? 0, b.discharge_mw ?? 0),
      0
    );

    const violations: string[] = [];
    if (currentExposure + proposedRevenue > maxDailyRevenue) {
      violations.push(
        `Daily revenue limit exceeded: $${(currentExposure + proposedRevenue).toFixed(0)} > $${maxDailyRevenue}`
      );
    }
    if (peakPositionMw > maxPositionMw) {
      violations.push(
        `Peak position ${peakPositionMw.toFixed(1)} MW exceeds limit ${maxPositionMw} MW`
      );
    }

    return {
      approved: violations.length === 0,
      violations,
      currentExposureDollars: currentExposure,
      proposedRevenueDollars: proposedRevenue,
      maxDailyRevenueDollars: maxDailyRevenue,
    };
  },
};

/**
 * solve_dispatch_pulp
 *
 * Calls POST /dispatch on the optimization service.  Unlike solve_dispatch
 * (which uses CVXPY and requires pre-fetched forecasts), this tool:
 *   1. Fetches the forecast internally from the forecasting service.
 *   2. Builds an uncertainty-adjusted price vector:
 *        adjusted[t] = p50[t] + spread_weight * (p90[t] - p10[t]) * direction
 *      where direction = +1 for discharge-favoured hours, -1 for charge-favoured.
 *      This makes the LP more conservative when the model is uncertain.
 *   3. Runs the PuLP LP and returns the signed net_mw schedule.
 *
 * The spread_weight is derived from forecast confidence: low confidence →
 * wider band → more conservative objective.
 */
export const solveDispatchPulp: ToolDefinition = {
  name: "solve_dispatch_pulp",
  description:
    "Run the PuLP LP dispatch optimizer with uncertainty-adjusted prices from p10/p50/p90 forecast bands. " +
    "Returns signed net_mw per hour (positive = discharge, negative = charge), SoC trajectory, and expected revenue.",
  inputSchema: {
    type: "object",
    properties: {
      hub: { type: "string", description: "Price node, e.g. HB_NORTH" },
      iso: { type: "string", default: "ERCOT" },
      market: { type: "string", default: "DA_ENERGY" },
      currentSocFrac: {
        type: "number",
        description: "Current battery state of charge as fraction of capacity (0-1)",
      },
      horizonHours: { type: "number", default: 24 },
      battery: {
        type: "object",
        description: "Battery parameters (all optional, service defaults apply)",
        properties: {
          capacity_mwh: { type: "number" },
          max_charge_mw: { type: "number" },
          max_discharge_mw: { type: "number" },
          eta_charge: { type: "number" },
          eta_discharge: { type: "number" },
          soc_min_frac: { type: "number" },
          soc_max_frac: { type: "number" },
          degradation_per_mwh: { type: "number" },
        },
      },
    },
    required: ["hub", "currentSocFrac"],
  },
  handler: async (input) => {
    const {
      hub,
      iso = "ERCOT",
      market = "DA_ENERGY",
      currentSocFrac,
      horizonHours = 24,
      battery = {},
      useRawLmp = false,
    } = input as {
      hub: string;
      iso?: string;
      market?: string;
      currentSocFrac: number;
      horizonHours?: number;
      battery?: Record<string, number>;
      useRawLmp?: boolean;
    };

    const response = await fetch(`${OPTIMIZATION_URL}/dispatch`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        hub,
        iso,
        market,
        current_soc_frac: currentSocFrac,
        horizon_hours: horizonHours,
        battery,
        use_raw_lmp: useRawLmp,
      }),
    });

    if (!response.ok) {
      throw new Error(
        `Dispatch service error: ${response.status} ${await response.text()}`
      );
    }

    return (await response.json()) as unknown;
  },
};

/**
 * update_soc
 *
 * Writes the latest executed SoC back to Redis after each MPC step.
 * The key is bess:soc:<assetId> and the value is the SoC as a fraction (0-1).
 * Also accumulates daily revenue exposure for risk checks.
 */
export const updateSoc: ToolDefinition = {
  name: "update_soc",
  description:
    "Persist the battery's current state of charge (as a fraction 0-1) to Redis " +
    "after executing an MPC step. Also updates daily revenue exposure.",
  inputSchema: {
    type: "object",
    properties: {
      assetId: { type: "string" },
      socFrac: {
        type: "number",
        description: "New SoC as fraction of capacity after executing the hour's command",
      },
      revenueExecutedDollars: {
        type: "number",
        description: "Actual revenue earned this step (used for risk tracking)",
        default: 0,
      },
    },
    required: ["assetId", "socFrac"],
  },
  handler: async (input) => {
    const { assetId, socFrac, revenueExecutedDollars = 0 } = input as {
      assetId: string;
      socFrac: number;
      revenueExecutedDollars?: number;
    };

    const redis = getRedisClient();

    // Write SoC — TTL 48h so stale values don't persist across restarts
    await redis.set(`bess:soc:${assetId}`, String(socFrac), "EX", 172800).catch(() => null);

    // Accumulate daily revenue exposure (reset each calendar day via TTL)
    const exposureKey = `risk:daily_exposure:${assetId}`;
    const existing = await redis.get(exposureKey).catch(() => null);
    const newExposure = (existing !== null ? parseFloat(existing) : 0) + revenueExecutedDollars;
    // TTL: seconds until midnight UTC
    const now = new Date();
    const secondsUntilMidnight =
      86400 - (now.getUTCHours() * 3600 + now.getUTCMinutes() * 60 + now.getUTCSeconds());
    await redis
      .set(exposureKey, String(newExposure), "EX", secondsUntilMidnight)
      .catch(() => null);

    return { assetId, socFrac, newDailyExposureDollars: newExposure };
  },
};
