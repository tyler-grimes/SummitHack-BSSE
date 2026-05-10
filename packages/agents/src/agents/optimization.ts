import { BaseAgent } from "./base-agent.js";
import type { ToolRegistry } from "../tools/tool-registry.js";

const SYSTEM_PROMPT = `You are the Optimization Agent for an energy trading optimization system.

Your role:
- Receive price forecasts and current battery state
- Use solve_dispatch_pulp to run the PuLP LP with uncertainty-adjusted prices (p10/p50/p90)
- Validate the resulting bid schedule against ISO constraints and risk limits
- After executing each MPC step, call update_soc to persist the new SoC to Redis
- Return the bid schedule with expected revenue breakdown

Workflow for each dispatch step:
1. Call get_battery_state to get current SoC
2. Call solve_dispatch_pulp with hub, iso, market, currentSocFrac, and battery params
3. Call validate_bids on the returned schedule
4. Call check_risk_limits before approving execution
5. Call update_soc with the final SoC from the schedule (soc_mwh[-1] / capacity_mwh)
6. Return the schedule JSON with solver_status, net_mw per hour, and total_forecast_revenue

Always validate bids before returning. Reject infeasible solutions.
The solve_dispatch_pulp tool handles uncertainty weighting internally — you do not need to pass p10/p90 manually.`;

export class OptimizationAgent extends BaseAgent {
  constructor(registry: ToolRegistry) {
    super(
      {
        id: "optimization",
        model: "claude-sonnet-4-6",
        systemPrompt: SYSTEM_PROMPT,
        maxIterations: 8,
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
        `Get battery state, run PuLP solver via solve_dispatch_pulp, validate bids, ` +
        `update SoC in Redis. Return dispatch schedule JSON.`
    );
  }

  /**
   * Execute a single MPC step: replan on fresh forecast, return first hour's command.
   * The caller (OrchestratorAgent) drives the hourly loop.
   */
  async mpcStep(
    assetId: string,
    hub: string,
    iso: string,
    market: string,
    currentSocFrac: number,
  ): Promise<string> {
    return this.runLoop(
      `MPC step for asset ${assetId}, hub ${hub}, ISO ${iso}, market ${market}. ` +
        `Current SoC: ${(currentSocFrac * 100).toFixed(1)}%. ` +
        `Run solve_dispatch_pulp to get a fresh 24h schedule. ` +
        `Validate the first hour's command. Check risk limits. ` +
        `Call update_soc with the SoC after executing the first hour only (soc_mwh[1] / capacity_mwh). ` +
        `Return JSON: { executedNetMw, newSocFrac, forecastRevenue, status }.`
    );
  }
}
