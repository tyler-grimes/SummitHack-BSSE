import "dotenv/config";
import { DEFAULT_SIM_CONFIG } from "./config.js";
import { runSimulation } from "./runner.js";
import { printReport } from "./report.js";

const config = {
  ...DEFAULT_SIM_CONFIG,
  startDate: process.env["SIM_START_DATE"] ?? DEFAULT_SIM_CONFIG.startDate,
  endDate: process.env["SIM_END_DATE"] ?? DEFAULT_SIM_CONFIG.endDate,
  assetId: process.env["SIM_ASSET_ID"] ?? DEFAULT_SIM_CONFIG.assetId,
  iso: process.env["SIM_ISO"] ?? DEFAULT_SIM_CONFIG.iso,
  node: process.env["SIM_NODE"] ?? DEFAULT_SIM_CONFIG.node,
};

console.log(
  `Starting simulation: ${config.assetId} on ${config.iso}/${config.node}` +
    ` from ${config.startDate} to ${config.endDate}`
);

runSimulation(config).then(printReport).catch((err: unknown) => {
  console.error("Simulation failed:", err);
  process.exit(1);
});
