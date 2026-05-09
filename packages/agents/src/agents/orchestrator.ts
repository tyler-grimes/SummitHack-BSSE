import { BaseAgent } from "./base-agent.js";
import type { ToolRegistry } from "../tools/tool-registry.js";

const SYSTEM_PROMPT = `You are the Orchestrator Agent for an energy trading optimization system.

Your role:
- Coordinate the full day-ahead (DA) and real-time (RT) market cycle for BESS assets
- Receive market intelligence events and decide when to act
- Spawn forecasting and optimization workflows
- Enforce risk limits — never allow execution if risk check fails
- All execution is in simulation/paper trading mode (DRY_RUN=true)

Decision framework:
1. Check risk limits first — always
2. Get price forecasts for relevant market windows
3. Run dispatch optimization against forecasts
4. Validate bids before any submission
5. Log expected P&L and reasoning

Return structured JSON with: { action, reasoning, expectedRevenueDollars, riskStatus }`;

export class OrchestratorAgent extends BaseAgent {
  constructor(registry: ToolRegistry) {
    super(
      {
        id: "orchestrator",
        model: "claude-sonnet-4-6",
        systemPrompt: SYSTEM_PROMPT,
        maxIterations: 15,
        maxTokens: 8192,
      },
      registry
    );
  }

  async run(input: string): Promise<string> {
    return this.runLoop(input);
  }

  async runDACycle(assetId: string, iso: string): Promise<string> {
    return this.runLoop(
      `Run the day-ahead market cycle for asset ${assetId} on ${iso}. ` +
        `Get forecasts, optimize dispatch, validate bids. Return full plan with expected revenue.`
    );
  }

  async runRTCycle(assetId: string, iso: string, triggerReason?: string): Promise<string> {
    const trigger = triggerReason ? ` Trigger: ${triggerReason}` : "";
    return this.runLoop(
      `Run real-time market cycle for asset ${assetId} on ${iso}.${trigger} ` +
        `Check risk limits, get RT price forecast, optimize next 2-hour window.`
    );
  }
}
