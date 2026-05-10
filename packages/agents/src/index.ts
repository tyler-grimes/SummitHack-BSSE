import "dotenv/config";
import { fileURLToPath } from "node:url";
import { ToolRegistry } from "./tools/tool-registry.js";
import { OrchestratorAgent } from "./agents/orchestrator.js";
import { fetchRealtimeLmp, fetchAncillaryPrices, detectAnomaly, parseIsoDocument } from "./tools/market-tools.js";
import { runPriceForecast, getForecastConfidence } from "./tools/forecasting-tools.js";
import {
  getBatteryState,
  solveDispatch,
  solveDispatchPulp,
  updateSoc,
  validateBids,
  checkRiskLimits,
} from "./tools/optimization-tools.js";

export function buildRegistry(): ToolRegistry {
  const registry = new ToolRegistry();

  // Market tools
  registry.register(fetchRealtimeLmp);
  registry.register(fetchAncillaryPrices);
  registry.register(detectAnomaly);
  registry.register(parseIsoDocument);

  // Forecasting tools
  registry.register(runPriceForecast);
  registry.register(getForecastConfidence);

  // Optimization + risk tools
  registry.register(getBatteryState);
  registry.register(solveDispatch);          // legacy CVXPY solver (kept for compatibility)
  registry.register(solveDispatchPulp);      // PuLP solver with uncertainty-adjusted prices
  registry.register(updateSoc);             // persist SoC to Redis after each MPC step
  registry.register(validateBids);
  registry.register(checkRiskLimits);

  return registry;
}

async function main() {
  const registry = buildRegistry();
  const orchestrator = new OrchestratorAgent(registry);

  const mode = process.env["RUN_MODE"] ?? "da";
  const assetId = process.env["SIM_ASSET_ID"] ?? "BESS-001";
  const iso = process.env["SIM_ISO"] ?? "ERCOT";
  const hub = process.env["SIM_NODE"] ?? "HB_NORTH";

  if (mode === "mpc") {
    const hours = parseInt(process.env["MPC_HOURS"] ?? "6", 10);
    console.log(`Running MPC loop: ${hours} steps for ${assetId} on ${iso}/${hub}...`);
    const result = await orchestrator.runMpcLoop(assetId, iso, hub, "RT_ENERGY", hours);
    console.log("MPC loop result:", result);
  } else if (mode === "rt") {
    console.log(`Running RT MPC step for ${assetId} on ${iso}/${hub}...`);
    const result = await orchestrator.runRTCycle(assetId, iso, hub);
    console.log("RT cycle result:", result);
  } else {
    console.log(`Running DA cycle for ${assetId} on ${iso}/${hub}...`);
    const result = await orchestrator.runDACycle(assetId, iso, hub);
    console.log("DA cycle result:", result);
  }
}

if (process.argv[1] === fileURLToPath(import.meta.url)) {
  main().catch(console.error);
}
