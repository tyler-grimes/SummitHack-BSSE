import { BaseAgent } from "./base-agent.js";
import type { ToolRegistry } from "../tools/tool-registry.js";

const SYSTEM_PROMPT = `You are the Forecasting Agent for an energy trading optimization system.

Your role:
- Call the forecasting service to generate price predictions for energy and ancillary markets
- Assess forecast confidence and flag low-confidence outputs
- Return structured probabilistic forecasts (mean + p10/p90 bands)

Always check model confidence before returning a forecast. If confidence < 0.7, flag it.`;

export class ForecastingAgent extends BaseAgent {
  constructor(registry: ToolRegistry) {
    super(
      {
        id: "forecasting",
        model: "claude-sonnet-4-6",
        systemPrompt: SYSTEM_PROMPT,
        maxIterations: 6,
      },
      registry
    );
  }

  async run(input: string): Promise<string> {
    return this.runLoop(input);
  }

  async forecast(iso: string, node: string, markets: string[], horizonHours: number): Promise<string> {
    return this.runLoop(
      `Generate price forecasts for ${iso} node ${node}, markets: ${markets.join(", ")}, ` +
        `horizon: ${horizonHours} hours. Check model confidence. Return structured forecast JSON.`
    );
  }
}
