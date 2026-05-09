import { BaseAgent } from "./base-agent.js";
import type { ToolRegistry } from "../tools/tool-registry.js";

const SYSTEM_PROMPT = `You are the Optimization Agent for an energy trading optimization system.

Your role:
- Receive price forecasts and current battery state
- Call the CVXPY optimization solver to compute the optimal dispatch schedule
- Validate the resulting bid schedule against ISO constraints
- Return the bid schedule with expected revenue breakdown

The solver co-optimizes across all provided markets simultaneously.
Always validate bids before returning. Reject infeasible solutions.`;

export class OptimizationAgent extends BaseAgent {
  constructor(registry: ToolRegistry) {
    super(
      {
        id: "optimization",
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

  async optimize(assetId: string, forecastJson: string): Promise<string> {
    return this.runLoop(
      `Optimize dispatch for asset ${assetId} using these forecasts: ${forecastJson}. ` +
        `Get battery state, run solver, validate bids. Return dispatch schedule JSON.`
    );
  }
}
