import "dotenv/config";
import { ToolRegistry } from "./tools/tool-registry.js";
import { OrchestratorAgent } from "./agents/orchestrator.js";
import { fetchRealtimeLmp, fetchAncillaryPrices, detectAnomaly, parseIsoDocument } from "./tools/market-tools.js";
import { runPriceForecast, getForecastConfidence } from "./tools/forecasting-tools.js";
import { getBatteryState, solveDispatch, validateBids, checkRiskLimits } from "./tools/optimization-tools.js";

function buildRegistry(): ToolRegistry {
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
  registry.register(solveDispatch);
  registry.register(validateBids);
  registry.register(checkRiskLimits);

  return registry;
}

async function main() {
  const registry = buildRegistry();

  const orchestrator = new OrchestratorAgent(registry);

  console.log("Agents initialized. Running DA cycle (simulation)...");

  const result = await orchestrator.runDACycle("BESS-001", "ERCOT");
  console.log("DA cycle result:", result);
}

main().catch(console.error);
